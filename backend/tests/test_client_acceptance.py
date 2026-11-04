"""„Klient zaakceptował” — akceptacja klienta na Tablicy (D1–D6, 16.10.2026).

Zgłoszenie Delivery Leada: dostał akceptację od klienta i nie wiedział, gdzie
ją zaznaczyć, żeby rekruter i Head of Recruitment dostali informację. Pomiar
na produkcji: 14 wejść na „Akceptację” w 60 dni, dzwonek przy 2; cztery
ostatnie przyszły z etapu szablonu Traffita („Po Interview”, order 11) i dały
0 dzwonków, bo resolver porównywał ``order`` etapów z dwóch szablonów.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
    StageCategoryEnum,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.services import pipeline_move_rules
from app.services import stage_handoff_recipients as handoff
from app.services import stage_notification_emitter as emitter
from app.services.notification_access import NOTIFICATION_SECTION_BY_TYPE
from app.services.notification_categories import (
    CATEGORY_BY_TYPE,
    CATEGORY_INFO,
    NotificationCategory,
)
from app.services.section_permissions import ProductSection
from tests.test_board_tasks import _cleanup, _login, _seed_user, _seed_world

# ── Jednostkowe ──────────────────────────────────────────────────────────────


def _def(name, enum, *, template_id=1, order=0, category="external"):
    return SimpleNamespace(
        name=name,
        legacy_enum_value=enum,
        category=category,
        terminal_type=None,
        template_id=template_id,
        order=order,
    )


AKCEPTACJA = _def("Akceptacja", "acceptance", template_id=1, order=9)
INTERVIEW = _def("Interview Klient", "client_interview", template_id=1, order=8)
UMOWA_WYSLANA = _def("Umowa wysłana", None, template_id=1, order=10)
TRAFFIT_PO_INTERVIEW = _def("Po Interview", "interview", template_id=9, order=11)
TRAFFIT_ZAAKCEPTOWANY = _def("Zaakceptowany", "acceptance", template_id=9, order=12)
TRAFFIT_ODRZUCONY = _def(
    "Odrzucony", "rejected", template_id=9, order=20, category="terminal"
)


def test_acceptance_is_its_own_handoff(monkeypatch) -> None:
    monkeypatch.setattr(handoff, "cpro_enabled_for_client", lambda _cid: False)
    assert (
        handoff.handoff_kind(AKCEPTACJA, client_id=7) == handoff.REASON_CLIENT_ACCEPTED
    )
    # Szablon Traffita niesie ten sam kod etapu.
    assert (
        handoff.handoff_kind(TRAFFIT_ZAAKCEPTOWANY, client_id=7)
        == handoff.REASON_CLIENT_ACCEPTED
    )
    # Akceptacja to informacja dla zespołu, nie zadanie ani zwrot.
    assert handoff.REASON_CLIENT_ACCEPTED not in handoff.TASK_REASONS
    assert handoff.REASON_CLIENT_ACCEPTED not in handoff.BACKWARD_REASONS
    terminal = _def("Zaakceptowany", "acceptance", category="terminal")
    assert handoff.handoff_kind(terminal, client_id=7) is None


@pytest.mark.parametrize(
    ("previous", "target", "backward"),
    [
        # Jeden szablon — decyduje `order`, jak dotąd.
        (INTERVIEW, AKCEPTACJA, False),
        (AKCEPTACJA, INTERVIEW, True),
        (AKCEPTACJA, UMOWA_WYSLANA, False),
        # Błąd z 12–16.10.2026: karta z Traffita („Po Interview”, order 11)
        # przesunięta na „Akceptację” (order 9) to ruch naprzód.
        (TRAFFIT_PO_INTERVIEW, AKCEPTACJA, False),
        # Ta sama kolumna w dwóch szablonach — ruch w bok, bez dzwonków.
        (TRAFFIT_ZAAKCEPTOWANY, AKCEPTACJA, True),
        # Cofnięcie między szablonami zostaje cofnięciem.
        (TRAFFIT_ZAAKCEPTOWANY, INTERVIEW, True),
        # Zamknięci są za „Zatrudnionym”: wyjście z nich nie jest ruchem naprzód,
        # zamknięcie z innego szablonu — jest (jak etap końcowy szablonu).
        (TRAFFIT_ODRZUCONY, AKCEPTACJA, True),
        (AKCEPTACJA, TRAFFIT_ODRZUCONY, False),
        (None, AKCEPTACJA, False),
    ],
)
def test_direction_across_templates_follows_board_columns(
    previous, target, backward
) -> None:
    assert handoff.is_backward_move(previous, target) is backward


def test_bell_says_who_accepted_when_and_opens_the_board() -> None:
    title, message, link = emitter._inapp_content(
        reason=handoff.REASON_CLIENT_ACCEPTED,
        candidate=SimpleNamespace(id=9),
        candidate_full_name="Jan Testowy",
        stage_display_name="Akceptacja",
        job=SimpleNamespace(id=3, title="ZOB-1 Java", working_title="Java · Spring"),
        mover=SimpleNamespace(name="Sandra S."),
        client_name="Bank Przykładowy",
        accepted_on=date(2026, 10, 15),
        planned_start_on=date(2026, 11, 1),
    )
    assert title == "Klient zaakceptował: Jan Testowy"
    assert "Klient Bank Przykładowy zaakceptował osobę Jan Testowy" in message
    assert "„Java · Spring”" in message
    assert "Zaznaczył(a) Sandra S., 15.10." in message
    assert "Planowany start: 01.11.2026." in message
    # „w ofercie” zostało w starym zdaniu reguły — tu mówimy o rekrutacji.
    assert "ofercie" not in message
    assert link == "/jobs/3?candidate=9"


def test_acceptance_bell_cannot_be_muted_and_belongs_to_the_pipeline() -> None:
    category = CATEGORY_BY_TYPE[NotificationType.client_accepted]
    assert category == NotificationCategory.acceptances
    assert CATEGORY_INFO[category].mandatory
    assert CATEGORY_INFO[category].label == "Akceptacje klienta"
    assert (
        NOTIFICATION_SECTION_BY_TYPE[NotificationType.client_accepted]
        == ProductSection.pipeline
    )


def test_acceptance_dates_only_with_the_acceptance_move() -> None:
    today = date(2026, 10, 16)
    check = pipeline_move_rules.assert_client_acceptance_dates
    check(PipelineStage.acceptance, None, None, today=today)
    check(PipelineStage.acceptance, date(2026, 10, 15), date(2026, 11, 1), today=today)
    check(PipelineStage.acceptance, today, today, today=today)
    check(PipelineStage.verified, None, None, today=today)

    with pytest.raises(HTTPException) as other_stage:
        check(PipelineStage.verified, today, None, today=today)
    assert other_stage.value.status_code == 422
    with pytest.raises(HTTPException) as future:
        check(PipelineStage.acceptance, date(2026, 10, 17), None, today=today)
    assert "z przyszłości" in future.value.detail
    with pytest.raises(HTTPException) as start:
        check(PipelineStage.acceptance, today, date(2026, 10, 15), today=today)
    assert "przed akceptacją" in start.value.detail
    # Bez daty akceptacji start liczy się od dziś.
    with pytest.raises(HTTPException):
        check(PipelineStage.acceptance, None, date(2026, 10, 1), today=today)


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


async def _add_acceptance_world(world: dict) -> int:
    """Etapy klienta szablonu rekrutacji + osobny szablon „z Traffita” z „Po
    Interview” na końcu (order wyższy niż „Akceptacja”). Zwraca id szablonu
    Traffita do sprzątania."""

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        for order, (key, name, enum) in enumerate(
            [
                ("interview", "Interview Klient", "client_interview"),
                ("acceptance", "Akceptacja", "acceptance"),
                ("contract_sent", "Umowa wysłana", None),
            ],
            start=6,
        ):
            stage_def = PipelineStageDef(
                template_id=world["template_id"],
                name=name,
                order=order,
                category=StageCategoryEnum.external,
                legacy_enum_value=enum,
            )
            db.add(stage_def)
            await db.flush()
            world["defs"][key] = stage_def.id
        traffit = PipelineTemplate(name=f"CA Traffit {unique}")
        db.add(traffit)
        await db.flush()
        po_interview = PipelineStageDef(
            template_id=traffit.id,
            name="Po Interview",
            order=50,
            category=StageCategoryEnum.internal,
            legacy_enum_value="interview",
        )
        db.add(po_interview)
        await db.flush()
        world["defs"]["traffit_po_interview"] = po_interview.id
        await db.commit()
        return traffit.id


async def _seed_pair_from_traffit(world: dict, recruiter_id: int) -> None:
    """Para z historią z Traffita: weryfikacja rekrutera, potem „Po Interview”
    z szablonu Traffita jako bieżący wiersz."""

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                CandidateStage(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    stage=PipelineStage.verified,
                    stage_def_id=world["defs"]["verified"],
                    moved_by=recruiter_id,
                    moved_at=now - timedelta(days=5),
                ),
                CandidateStage(
                    candidate_id=world["candidate_id"],
                    job_id=world["job_id"],
                    stage=PipelineStage.interview,
                    stage_def_id=world["defs"]["traffit_po_interview"],
                    moved_at=now - timedelta(days=1),
                    external_source="traffit",
                ),
            ]
        )
        await db.commit()


async def _acceptance_bells(user_id: int, candidate_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        stage_ids = select(CandidateStage.id).where(
            CandidateStage.candidate_id == candidate_id
        )
        rows = await db.scalars(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.notification_type == NotificationType.client_accepted,
                Notification.related_entity_type == "candidate_stage",
                Notification.related_entity_id.in_(stage_ids),
            )
            .order_by(Notification.id)
        )
        return list(rows.all())


async def _cleanup_traffit(template_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(PipelineStageDef).where(PipelineStageDef.template_id == template_id)
        )
        await db.execute(
            delete(PipelineTemplate).where(PipelineTemplate.id == template_id)
        )
        await db.commit()


@pytest.mark.asyncio
async def test_acceptance_from_a_traffit_stage_rings_the_team_and_undo_closes_bells(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    traffit_id = await _add_acceptance_world(world)
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    owner_id, _ = await _seed_user(UserRole.recruiter)
    rec_id, _ = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    hor_id, _ = await _seed_user(UserRole.head_of_recruitment)
    dl = await _login(api_client, dl_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, jid)
        job.recruiter_id = owner_id
        job.delivery_lead_id = dl_id
        await db.commit()
    accepted_on = business_today() - timedelta(days=1)
    start_on = business_today() + timedelta(days=14)
    try:
        await _seed_pair_from_traffit(world, rec_id)

        # Podgląd w oknie: ta sama lista co dzwonek, bez osoby, która patrzy.
        preview = await api_client.get(
            "/api/pipeline/client-acceptance/recipients",
            headers=dl,
            params={"job_id": jid, "candidate_id": cid},
        )
        assert preview.status_code == 200, preview.text
        roles = {r["user_id"]: r["role"] for r in preview.json()["recipients"]}
        assert roles[rec_id] == "recruiter"
        assert roles[owner_id] == "owner"
        assert roles[hor_id] == "head_of_recruitment"
        assert dl_id not in roles

        resp = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "stage_def_id": world["defs"]["acceptance"],
                "client_accepted_on": accepted_on.isoformat(),
                "planned_start_on": start_on.isoformat(),
            },
        )
        assert resp.status_code == 200, resp.text
        async with AsyncSessionLocal() as db:
            row = await db.get(CandidateStage, resp.json()["id"])
            assert row.client_accepted_on == accepted_on
            assert row.planned_start_on == start_on

        for uid in (owner_id, rec_id, hor_id):
            bells = await _acceptance_bells(uid, cid)
            assert len(bells) == 1, uid
            assert bells[0].title.startswith("Klient zaakceptował:")
            assert bells[0].link == f"/jobs/{jid}?candidate={cid}"
            assert f"{accepted_on:%d.%m}" in bells[0].message
        # Delivery Lead sam zaznaczył akceptację.
        assert await _acceptance_bells(dl_id, cid) == []

        # Karta na Tablicy niesie akceptację: kiedy i kto.
        board = await api_client.get(f"/api/pipeline/kanban/{jid}", headers=dl)
        assert board.status_code == 200, board.text
        items = [
            it
            for column in board.json()["columns"]
            for it in column["items"]
            if it["candidate_id"] == cid
        ]
        assert items[0]["client_acceptance"]["accepted_on"] == accepted_on.isoformat()
        assert items[0]["client_acceptance"]["planned_start_on"] == start_on.isoformat()

        # Przełącznik „Umowa wysłana” tam i z powrotem: powrót na „Akceptację”
        # nie jest nową akceptacją — data i autor zostają z okna.
        for key in ("contract_sent", "acceptance"):
            step = await api_client.post(
                "/api/pipeline/move",
                headers=dl,
                json={
                    "candidate_id": cid,
                    "job_id": jid,
                    "stage_def_id": world["defs"][key],
                },
            )
            assert step.status_code == 200, step.text
        async with AsyncSessionLocal() as db:
            back_row = await db.get(CandidateStage, step.json()["id"])
            assert back_row.client_accepted_on is None
        board = await api_client.get(f"/api/pipeline/kanban/{jid}", headers=dl)
        items = [
            it
            for column in board.json()["columns"]
            for it in column["items"]
            if it["candidate_id"] == cid
        ]
        assert items[0]["client_acceptance"]["accepted_on"] == accepted_on.isoformat()
        assert items[0]["client_acceptance"]["stage_id"] == resp.json()["id"]
        for uid in (owner_id, rec_id, hor_id):
            assert len(await _acceptance_bells(uid, cid)) == 1, uid

        # „Cofnij akceptację klienta”: karta wraca na rozmowę, dzwonki gasną.
        back = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "stage_def_id": world["defs"]["interview"],
            },
        )
        assert back.status_code == 200, back.text
        for uid in (owner_id, rec_id, hor_id):
            bells = await _acceptance_bells(uid, cid)
            assert [b.is_read for b in bells] == [True], uid
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Notification).where(
                    Notification.user_id.in_([owner_id, rec_id, dl_id, hor_id])
                )
            )
            await db.commit()
        await _cleanup(world, [owner_id, rec_id, dl_id, hor_id])
        await _cleanup_traffit(traffit_id)


@pytest.mark.asyncio
async def test_acceptance_fields_on_another_stage_are_refused(
    api_client: AsyncClient,
) -> None:
    world = await _seed_world()
    traffit_id = await _add_acceptance_world(world)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.delivery_lead_id = dl_id
        await db.commit()
    try:
        await _seed_pair_from_traffit(world, dl_id)
        resp = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": world["defs"]["interview"],
                "client_accepted_on": business_today().isoformat(),
            },
        )
        assert resp.status_code == 422, resp.text
        assert "Klient zaakceptował" in resp.text

        future = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": world["candidate_id"],
                "job_id": world["job_id"],
                "stage_def_id": world["defs"]["acceptance"],
                "client_accepted_on": (
                    business_today() + timedelta(days=1)
                ).isoformat(),
            },
        )
        assert future.status_code == 422, future.text
    finally:
        await _cleanup(world, [dl_id])
        await _cleanup_traffit(traffit_id)
