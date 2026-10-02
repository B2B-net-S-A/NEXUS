"""Dzwonek przy przekazaniu karty z rąk do rąk (zgłoszenie z testów 02.10.2026).

Rekruter przesunął kandydata na „QC CV”, Delivery Lead wysłał CV do klienta
i żadna z dwóch osób nie dostała powiadomienia: etap „QC CV” nie miał żadnej
reguły, a „CV wysłane” powiadamiało wyłącznie osobę z `jobs.recruiter_id`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.pipeline_template import PipelineStageDef, StageCategoryEnum
from app.models.recruitment_pipeline import CandidateStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services import cpro_sender
from app.services import stage_handoff_recipients as handoff
from app.services import stage_notification_emitter as emitter
from tests.test_board_tasks import (
    _cleanup,
    _login,
    _move,
    _seed_user,
    _seed_world,
    clear_cpro_sender,
    restore_cpro_sender,
    seed_entry_row,
)

# ── Jednostkowe: który etap jest przekazaniem ────────────────────────────────


def _def(name: str, enum: str | None, category: str = "internal"):
    return SimpleNamespace(
        name=name, legacy_enum_value=enum, category=category, terminal_type=None
    )


@pytest.mark.parametrize(
    ("stage", "nordea", "expected"),
    [
        (_def("QC CV", "interview"), False, handoff.REASON_DL_REVIEW),
        (_def("Przepuszczony przez DZ", "interview"), False, handoff.REASON_DL_REVIEW),
        # U Nordei QC CV poprawia rekruter — przekazaniem jest kolejka Cpro.
        (_def("QC CV", "interview"), True, None),
        (_def("Wysłać do Cpro", None), True, handoff.REASON_CPRO_QUEUE),
        (_def("NORDEA: Wysłać do Cpro", "screening"), True, handoff.REASON_CPRO_QUEUE),
        (_def("Wysłać do Cpro", None), False, None),
        (_def("CV Wysłane", "cv_sent", "external"), False, handoff.REASON_CV_SENT),
        (
            _def("Wysłany do Klienta", "cv_sent", "external"),
            True,
            handoff.REASON_CV_SENT,
        ),
        (_def("Zweryfikowany", "verified"), False, None),
        (_def("Interview Klient", "client_interview", "external"), False, None),
        # Etap końcowy z „QC” w nazwie to zamknięcie, nie kolumna QC CV.
        (_def("Odrzucony po QC", "rejected", "terminal"), False, None),
        # Etapy-odznaki bez reguły z zasiewu — u każdego klienta.
        (_def("Preparation Meeting", None), False, handoff.REASON_STAGE_REACHED),
        (_def("Interview - Prep", "interview"), True, handoff.REASON_STAGE_REACHED),
        (
            _def("Umowa wysłana", None, "external"),
            False,
            handoff.REASON_STAGE_REACHED,
        ),
        (
            _def("Umowa podpisana", None, "external"),
            True,
            handoff.REASON_STAGE_REACHED,
        ),
        (_def("Akceptacja", "acceptance", "external"), False, None),
        (_def("Odrzucony po prepie", "rejected", "terminal"), False, None),
    ],
)
def test_handoff_kind(monkeypatch, stage, nordea, expected) -> None:
    monkeypatch.setattr(handoff, "cpro_enabled_for_client", lambda _cid: nordea)
    assert handoff.handoff_kind(stage, client_id=7) == expected


def test_return_from_the_cpro_queue_is_a_handoff_only_at_nordea(monkeypatch) -> None:
    qc, cpro = _def("QC CV", "interview"), _def("Wysłać do Cpro", None)
    verified = _def("Zweryfikowany", "verified")
    monkeypatch.setattr(handoff, "cpro_enabled_for_client", lambda _cid: True)
    assert (
        handoff.handoff_kind(qc, client_id=7, previous_def=cpro)
        == handoff.REASON_CPRO_RETURNED
    )
    # Zwykłe wejście do „QC CV” u Nordei to praca rekrutera, nie przekazanie.
    assert handoff.handoff_kind(qc, client_id=7, previous_def=verified) is None
    monkeypatch.setattr(handoff, "cpro_enabled_for_client", lambda _cid: False)
    assert (
        handoff.handoff_kind(qc, client_id=7, previous_def=cpro)
        == handoff.REASON_DL_REVIEW
    )


def test_waiting_tasks_cannot_be_muted_and_cv_sent_stays_a_stage_move() -> None:
    """Zadanie czekające na odbiorcę idzie typem z kategorii „Wzmianki”."""
    from app.services.notification_categories import (
        CATEGORY_BY_TYPE,
        CATEGORY_INFO,
        NotificationCategory,
    )

    assert handoff.TASK_REASONS == {
        handoff.REASON_DL_REVIEW,
        handoff.REASON_CPRO_QUEUE,
        handoff.REASON_CPRO_RETURNED,
    }
    category = CATEGORY_BY_TYPE[NotificationType.board_task_waiting]
    assert category == NotificationCategory.mentions
    assert CATEGORY_INFO[category].mandatory
    assert not CATEGORY_INFO[CATEGORY_BY_TYPE[NotificationType.stage_rule]].mandatory
    # Wejście na etap-odznakę to informacja, nie zadanie.
    assert handoff.REASON_STAGE_REACHED not in handoff.TASK_REASONS


def test_migration_and_entrypoint_add_the_notification_type() -> None:
    backend = Path(__file__).resolve().parents[1]
    statement = (
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'board_task_waiting'"
    )
    migration = (
        backend / "alembic" / "versions" / "0408_board_task_waiting_notif.py"
    ).read_text(encoding="utf-8")
    assert statement in " ".join(migration.split())
    assert statement in (backend / "entrypoint.sh").read_text(encoding="utf-8")


def _content(reason, *, mover=SimpleNamespace(name="Sandra S.")):
    return emitter._inapp_content(
        reason=reason,
        candidate=SimpleNamespace(id=9),
        candidate_full_name="Jan Testowy",
        stage_display_name="CV Wysłane",
        job=SimpleNamespace(id=3, title="ZOB-1 Java", working_title="Java · Spring"),
        mover=mover,
    )


def test_handoff_bell_says_what_to_do_and_opens_the_person_on_the_board() -> None:
    title, message, link = _content(handoff.REASON_DL_REVIEW)
    assert title == "CV do przeglądu: Jan Testowy"
    assert "Sandra S. przekazał(a) CV kandydata Jan Testowy do QC" in message
    assert "„Java · Spring”" in message
    assert link == "/jobs/3?candidate=9"

    title, message, link = _content(handoff.REASON_CV_SENT)
    assert title == "CV wysłane: Jan Testowy"
    assert "Sandra S. wysłał(a) CV kandydata Jan Testowy" in message
    assert link == "/jobs/3?candidate=9"

    title, _message, link = _content(handoff.REASON_CPRO_QUEUE)
    assert title == "Do wrzucenia do Cpro: Jan Testowy"
    assert link == "/jobs/3?candidate=9"

    title, message, link = _content(handoff.REASON_CPRO_RETURNED)
    assert title == "Wrócił z kolejki Cpro: Jan Testowy"
    assert "Sandra S. zwrócił(a) kandydata Jan Testowy z kolejki Cpro" in message
    assert link == "/jobs/3?candidate=9"


def test_badge_stage_bell_names_the_stage_and_opens_the_board() -> None:
    title, message, link = emitter._inapp_content(
        reason=handoff.REASON_STAGE_REACHED,
        candidate=SimpleNamespace(id=9),
        candidate_full_name="Jan Testowy",
        stage_display_name="Umowa podpisana",
        job=SimpleNamespace(id=3, title="ZOB-1 Java", working_title="Java · Spring"),
        mover=SimpleNamespace(name="Klaudia K."),
    )
    assert title == "Umowa podpisana: Jan Testowy"
    assert "na etapie „Umowa podpisana” w rekrutacji „Java · Spring”" in message
    assert "Klaudia K." in message
    assert link == "/jobs/3?candidate=9"


def test_plain_stage_rule_keeps_its_wording() -> None:
    title, message, link = _content(None)
    assert title == "Kandydat Jan Testowy → CV Wysłane"
    assert "przez Sandra S." in message
    assert link == "/candidates/9"


# ── Integracyjne: prawdziwy ruch przez /api/pipeline/move ────────────────────


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _stage_bells(user_id: int, candidate_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        stage_ids = select(CandidateStage.id).where(
            CandidateStage.candidate_id == candidate_id
        )
        rows = await db.scalars(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type.in_(
                    (NotificationType.stage_rule, NotificationType.board_task_waiting)
                ),
                Notification.related_entity_type == "candidate_stage",
                Notification.related_entity_id.in_(stage_ids),
            )
            .order_by(Notification.id)
        )
        return list(rows.all())


async def _seed_screening(world: dict, moved_by: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                stage="screening",
                stage_def_id=world["defs"]["screening"],
                moved_by=moved_by,
                moved_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_qc_rings_the_delivery_lead_and_cv_sent_rings_the_recruiter(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scenariusz ze zgłoszenia: etapy szablonu nie mają ŻADNEJ reguły, a
    prowadzącym rekrutację jest ktoś inny niż osoba pracująca z kandydatem."""

    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    owner_id, _ = await _seed_user(UserRole.recruiter)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, jid)
        job.recruiter_id = owner_id
        job.delivery_lead_id = dl_id
        await db.commit()
    try:
        await _seed_screening(world, rec_id)
        await _move(
            api_client,
            rec,
            world,
            "verified",
            expected_rate_value="140",
            expected_rate_unit="hourly",
            expected_rate_currency="PLN",
        )
        assert await _stage_bells(dl_id, cid) == []

        await _move(api_client, rec, world, "qc")
        dl_bells = await _stage_bells(dl_id, cid)
        assert [b.title.split(":")[0] for b in dl_bells] == ["CV do przeglądu"]
        assert dl_bells[0].notification_type == NotificationType.board_task_waiting
        assert dl_bells[0].link == f"/jobs/{jid}?candidate={cid}"
        # Rekruter sam przesunął kartę — o własnym ruchu dzwonka nie dostaje.
        assert await _stage_bells(rec_id, cid) == []

        await _move(
            api_client,
            dl,
            world,
            "cv_sent",
            client_rate_value="170",
            client_rate_unit="hourly",
            client_rate_currency="PLN",
        )
        rec_bells = await _stage_bells(rec_id, cid)
        assert [b.title.split(":")[0] for b in rec_bells] == ["CV wysłane"]
        assert rec_bells[0].notification_type == NotificationType.stage_rule
        assert rec_bells[0].link == f"/jobs/{jid}?candidate={cid}"
        # DL nie dostaje dzwonka o własnej wysyłce; nadal ma jeden, z QC.
        assert len(await _stage_bells(dl_id, cid)) == 1
    finally:
        await _cleanup(world, [owner_id, rec_id, dl_id])


@pytest.mark.asyncio
async def test_qc_without_job_delivery_lead_rings_the_client_portfolio(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_in_id, _ = await _seed_user(UserRole.delivery_lead)
    dl_out_id, _ = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    cid = world["candidate_id"]
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_in_id, client_id=world["client_id"]
            )
        )
        await db.commit()
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        assert len(await _stage_bells(dl_in_id, cid)) == 1
        assert await _stage_bells(dl_out_id, cid) == []
    finally:
        await _cleanup(world, [rec_id, dl_in_id, dl_out_id])


@pytest.mark.asyncio
async def test_nordea_cpro_queue_rings_the_cpro_sender_not_the_delivery_lead(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    admin_id, admin_creds = await _seed_user(UserRole.admin)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    sender_id, _ = await _seed_user(UserRole.recruiter)
    dl_id, _ = await _seed_user(UserRole.delivery_lead)
    admin = await _login(api_client, admin_creds)
    rec = await _login(api_client, rec_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    async with AsyncSessionLocal() as db:
        (await db.get(Job, jid)).delivery_lead_id = dl_id
        await db.commit()
    try:
        async with restore_cpro_sender():
            await clear_cpro_sender()
            put = await api_client.put(
                "/api/board-tasks/cpro/sender",
                headers=admin,
                json={"user_id": sender_id, "until": None},
            )
            assert put.status_code == 200, put.text
            async with AsyncSessionLocal() as db:
                assert (await cpro_sender.effective_sender(db)).user_id == sender_id

            await _move(api_client, rec, world, "verified")
            await _move(api_client, rec, world, "qc")
            # U Nordei QC CV poprawia rekruter — DL nie dostaje przeglądu.
            assert await _stage_bells(dl_id, cid) == []

            await _move(api_client, rec, world, "cpro")
            bells = await _stage_bells(sender_id, cid)
            assert [b.title.split(":")[0] for b in bells] == ["Do wrzucenia do Cpro"]
            assert bells[0].notification_type == NotificationType.board_task_waiting
            assert bells[0].link == f"/jobs/{jid}?candidate={cid}"
            assert await _stage_bells(dl_id, cid) == []
    finally:
        await _cleanup(world, [admin_id, rec_id, sender_id, dl_id])


# ── Uzupełnienie 02.10.2026: zwrot z Cpro, osoba przekazująca, wyciszenia ────


@pytest.mark.asyncio
async def test_cv_sent_also_rings_the_person_who_handed_the_card_over(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Kartę do DL przekazuje nieraz ktoś inny niż pierwszy weryfikator —
    obie osoby mają wiedzieć, że CV poszło do klienta."""

    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    verifier_id, verifier_creds = await _seed_user(UserRole.recruiter)
    hander_id, hander_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    verifier = await _login(api_client, verifier_creds)
    hander = await _login(api_client, hander_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    async with AsyncSessionLocal() as db:
        (await db.get(Job, jid)).delivery_lead_id = dl_id
        await db.commit()
    try:
        await _seed_screening(world, verifier_id)
        await _move(api_client, verifier, world, "verified")
        await _move(api_client, hander, world, "qc")
        await _move(
            api_client,
            dl,
            world,
            "cv_sent",
            client_rate_value="170",
            client_rate_unit="hourly",
            client_rate_currency="PLN",
        )
        for user_id in (verifier_id, hander_id):
            sent = [
                b
                for b in await _stage_bells(user_id, cid)
                if b.title.startswith("CV wysłane")
            ]
            assert len(sent) == 1, user_id
            assert sent[0].notification_type == NotificationType.stage_rule
    finally:
        await _cleanup(world, [verifier_id, hander_id, dl_id])


@pytest.mark.asyncio
async def test_muted_pipeline_category_does_not_hide_the_review_request(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Wyciszone „Ruchy w rekrutacjach” gaszą informację o ruchu, ale nie
    zadanie: Delivery Lead nadal widzi, że ktoś czeka na przegląd."""

    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    muted = {"pipeline": datetime.now(timezone.utc).isoformat()}
    async with AsyncSessionLocal() as db:
        (await db.get(Job, jid)).delivery_lead_id = dl_id
        (await db.get(User, dl_id)).muted_notification_categories = muted
        (await db.get(User, rec_id)).muted_notification_categories = muted
        await db.commit()
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        dl_bells = await _stage_bells(dl_id, cid)
        assert [b.notification_type for b in dl_bells] == [
            NotificationType.board_task_waiting
        ]

        await _move(
            api_client,
            dl,
            world,
            "cv_sent",
            client_rate_value="170",
            client_rate_unit="hourly",
            client_rate_currency="PLN",
        )
        # „CV wysłane” to informacja o ruchu — wyciszenie rekrutera ją gasi.
        assert await _stage_bells(rec_id, cid) == []
    finally:
        await _cleanup(world, [rec_id, dl_id])


@pytest.mark.asyncio
async def test_return_from_the_cpro_queue_rings_the_person_who_queued_the_card(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    admin_id, admin_creds = await _seed_user(UserRole.admin)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    sender_id, sender_creds = await _seed_user(UserRole.recruiter)
    admin = await _login(api_client, admin_creds)
    rec = await _login(api_client, rec_creds)
    sender = await _login(api_client, sender_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    try:
        async with restore_cpro_sender():
            await clear_cpro_sender()
            put = await api_client.put(
                "/api/board-tasks/cpro/sender",
                headers=admin,
                json={"user_id": sender_id, "until": None},
            )
            assert put.status_code == 200, put.text

            await _move(api_client, rec, world, "verified")
            await _move(api_client, rec, world, "qc")
            await _move(api_client, rec, world, "cpro")
            assert await _stage_bells(rec_id, cid) == []

            # „Zwróć do rekrutera”: ruch wstecz, a mimo to dzwonek.
            await _move(api_client, sender, world, "qc")
            bells = await _stage_bells(rec_id, cid)
            assert [b.title.split(":")[0] for b in bells] == ["Wrócił z kolejki Cpro"]
            assert bells[0].notification_type == NotificationType.board_task_waiting
            assert bells[0].link == f"/jobs/{jid}?candidate={cid}"
            # Osoba od Cpro nie dostaje dzwonka o własnym zwrocie.
            assert len(await _stage_bells(sender_id, cid)) == 1

            # Zwykłe cofnięcie karty nadal nikogo nie powiadamia.
            await _move(api_client, rec, world, "verified")
            assert len(await _stage_bells(rec_id, cid)) == 1
            assert len(await _stage_bells(sender_id, cid)) == 1
    finally:
        await _cleanup(world, [admin_id, rec_id, sender_id])


async def _add_badge_stages(world: dict) -> None:
    """Etapy-odznaki z „Default B2B”, których zasiew reguł nie objął."""

    async with AsyncSessionLocal() as db:
        for order, (key, name) in enumerate(
            [
                ("prep", "Preparation Meeting"),
                ("contract_sent", "Umowa wysłana"),
                ("contract_signed", "Umowa podpisana"),
            ],
            start=10,
        ):
            stage_def = PipelineStageDef(
                template_id=world["template_id"],
                name=name,
                order=order,
                category=StageCategoryEnum.external,
                legacy_enum_value=None,
            )
            db.add(stage_def)
            await db.flush()
            world["defs"][key] = stage_def.id
        await db.commit()


@pytest.mark.asyncio
async def test_prep_and_contract_stages_ring_the_recruiters_and_the_delivery_lead(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """„Preparation Meeting”, „Umowa wysłana” i „Umowa podpisana” nie mają
    żadnej reguły, a i tak powiadamiają osoby pracujące z kandydatem."""

    world = await _seed_world()
    await _add_badge_stages(world)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    owner_id, _ = await _seed_user(UserRole.recruiter)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, jid)
        job.recruiter_id = owner_id
        job.delivery_lead_id = dl_id
        await db.commit()

    def titles(bells: list[Notification]) -> list[str]:
        return [b.title.split(":")[0] for b in bells]

    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        await _move(
            api_client,
            dl,
            world,
            "cv_sent",
            client_rate_value="170",
            client_rate_unit="hourly",
            client_rate_currency="PLN",
        )
        # Dotąd: DL ma prośbę o przegląd, rekruter — „CV wysłane”.
        assert titles(await _stage_bells(dl_id, cid)) == ["CV do przeglądu"]
        assert titles(await _stage_bells(rec_id, cid)) == ["CV wysłane"]

        await _move(api_client, rec, world, "prep")
        dl_bells = await _stage_bells(dl_id, cid)
        assert titles(dl_bells) == ["CV do przeglądu", "Preparation Meeting"]
        assert dl_bells[-1].notification_type == NotificationType.stage_rule
        assert dl_bells[-1].link == f"/jobs/{jid}?candidate={cid}"
        assert titles(await _stage_bells(owner_id, cid))[-1] == "Preparation Meeting"
        # Rekruter sam przesunął kartę.
        assert titles(await _stage_bells(rec_id, cid)) == ["CV wysłane"]

        await _move(api_client, dl, world, "contract_sent")
        assert titles(await _stage_bells(rec_id, cid)) == [
            "CV wysłane",
            "Umowa wysłana",
        ]
        assert titles(await _stage_bells(owner_id, cid))[-1] == "Umowa wysłana"
        assert len(await _stage_bells(dl_id, cid)) == 2

        await _move(api_client, dl, world, "contract_signed")
        assert titles(await _stage_bells(rec_id, cid)) == [
            "CV wysłane",
            "Umowa wysłana",
            "Umowa podpisana",
        ]
        # Cofnięcie karty nikogo nie powiadamia.
        await _move(api_client, dl, world, "contract_sent")
        assert len(await _stage_bells(rec_id, cid)) == 3
    finally:
        await _cleanup(world, [owner_id, rec_id, dl_id])
