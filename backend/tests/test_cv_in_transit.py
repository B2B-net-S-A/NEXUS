"""„Twoje CV w drodze” — lista rekrutera w panelu „Czeka na Ciebie” (02.10.2026).

Po przekazaniu CV do QC rekruter nie widział na pulpicie nic: panel pokazywał
przegląd tylko Delivery Leadowi, a kolejkę tylko osobie od Cpro. Lista jest
liczona przy odczycie z najnowszego wiersza pary i trafia do rekrutera
kandydata albo osoby, która przekazała kartę dalej.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import UserRole
from app.services import cv_in_transit as svc
from app.services import dl_send_queue
from tests.test_board_tasks import (
    CPRO_RATE,
    _cleanup,
    _login,
    _move,
    _seed_user,
    _seed_world,
    clear_cpro_sender,
    restore_cpro_sender,
    seed_entry_row,
)
from tests.test_dl_send_queue import _add_qc_run, _put_in_qc

# ── Jednostkowe: rodzaj wpisu z kolumn Tablicy ───────────────────────────────


def _kind(**over) -> str | None:
    args = dict(
        column="verified",
        badge=None,
        prev_column=None,
        prev_badge=None,
        nordea=False,
        ended_by=None,
    )
    args.update(over)
    return svc.classify(**args)


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (dict(column="cv_sent"), svc.KIND_SENT),
        (dict(column="cv_qc", badge="qc"), svc.KIND_IN_REVIEW),
        # U Nordei „QC CV” to praca rekrutera, nie przegląd u DL.
        # Od 13.10.2026 „QC CV” u Nordei to też przegląd Delivery Leada.
        (dict(column="cv_qc", badge="qc", nordea=True), svc.KIND_IN_REVIEW),
        (dict(column="cv_qc", badge="cpro", nordea=True), svc.KIND_CPRO_QUEUE),
        (dict(column="cv_qc", badge="cpro"), None),
        (
            dict(
                column="cv_qc",
                badge="qc",
                nordea=True,
                prev_column="cv_qc",
                prev_badge="cpro",
            ),
            svc.KIND_CPRO_RETURNED,
        ),
        (dict(column="closed", ended_by="delivery_lead"), svc.KIND_REJECTED_BY_DL),
        (dict(column="closed", ended_by="recruiter"), None),
        (dict(column="closed", ended_by="candidate"), None),
        (dict(column="verified", prev_column="cv_qc"), svc.KIND_SENT_BACK),
        (dict(column="screening", prev_column="cv_qc"), svc.KIND_SENT_BACK),
        # Zwykły ruch w przód i etap spoza szablonu nie są wpisem.
        (dict(column="verified", prev_column="screening"), None),
        (dict(column="client_interview", prev_column="cv_sent"), None),
        (dict(column=None), None),
    ],
)
def test_classify(args: dict, expected: str | None) -> None:
    assert _kind(**args) == expected


def test_transit_row_carries_the_fix_list() -> None:
    """D6 (08.10.2026): wiersz „wróciło” niesie pola wskazane przez DL."""
    row = svc.TransitRow(
        kind=svc.KIND_SENT_BACK,
        stage_id=1,
        candidate_id=2,
        candidate_name="Jan",
        job_id=3,
        job_title="Java",
        job_working_title=None,
        client_name=None,
        since=datetime.now(timezone.utc),
        fix_labels=("CV firmowe",),
    )
    assert row.fix_labels == ("CV firmowe",)
    from app.api.board_tasks import CvTransitRow
    from dataclasses import asdict

    assert CvTransitRow(**asdict(row)).fix_labels == ["CV firmowe"]


# Środa; karta weszła do „QC CV” w poniedziałek tego samego tygodnia.
_ENTERED = datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc)
_WEDNESDAY = datetime(2026, 3, 4, 9, 0, tzinfo=timezone.utc)


def _review(**over) -> svc.ReviewState:
    args = dict(
        since=_ENTERED,
        status={"status": "passed", "blocking_failed": 0, "ok_at": _WEDNESDAY},
        imported=False,
        today=date(2026, 3, 6),
    )
    args.update(over)
    return svc.review_state(**args)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ({"status": "failed", "blocking_failed": 2, "ok_at": None}, "failed"),
        ({"status": "unchecked", "blocking_failed": 0, "ok_at": None}, "unchecked"),
        # Para bez wpisu QC = nikt jeszcze nie sprawdzał.
        (None, "unchecked"),
    ],
)
def test_review_with_open_qc_is_the_recruiters_move(
    status: dict | None, expected: str
) -> None:
    """13.10.2026: dopóki QC nie przeszło, karta w „QC CV” nie czeka na
    Delivery Leada — nie ma czego przypominać, choćby stała tydzień."""
    state = _review(status=status, today=date(2026, 3, 20))
    assert state.qc_status == expected
    assert state.ready_since is None
    assert state.waiting_workdays == 0
    assert state.can_nudge is False


def test_review_can_be_nudged_after_two_workdays_from_readiness() -> None:
    """Czas biegnie od zaliczenia QC (środa), nie od wejścia do kolumny
    (poniedziałek) — poprawki rekrutera nie obciążają Delivery Leada."""
    thursday = _review(today=date(2026, 3, 5))
    assert thursday.ready_since == _WEDNESDAY
    assert thursday.waiting_workdays == 1
    assert thursday.can_nudge is False

    friday = _review()
    assert friday.qc_status == "passed"
    assert friday.waiting_workdays == dl_send_queue.LATE_WORKDAYS
    assert friday.can_nudge is True

    # Obejście QC sprzed wejścia do kolumny: gotowe od wejścia.
    overridden = _review(
        status={
            "status": "overridden",
            "blocking_failed": 1,
            "ok_at": _ENTERED - timedelta(days=3),
        },
        today=date(2026, 3, 4),
    )
    assert overridden.ready_since == _ENTERED
    assert overridden.can_nudge is True


def test_review_set_by_the_traffit_import_is_never_nudged() -> None:
    """Etap z importu Traffita nie budzi Delivery Leada
    (`dl_send_queue.counts_for_reviewer`) — przypomnienie też nie."""
    state = _review(imported=True, today=date(2026, 3, 20))
    assert state.ready_since == _WEDNESDAY
    assert state.can_nudge is False


def test_reviewers_label_names_one_person_and_counts_the_rest() -> None:
    assert svc.reviewers_label(["Marta Kowalczyk"]) == "Marta Kowalczyk"
    assert (
        svc.reviewers_label(["Adam Wrona", "Marta Kowalczyk", "Jan Dąb"])
        == "Adam Wrona +2"
    )


def test_transit_row_carries_the_review_state_to_the_api() -> None:
    from dataclasses import asdict

    from app.api.board_tasks import CvTransitRow

    base = dict(
        stage_id=1,
        candidate_id=2,
        candidate_name="Jan",
        job_id=3,
        job_title="Java",
        job_working_title=None,
        client_name=None,
        since=_ENTERED,
    )
    review = CvTransitRow(
        **asdict(
            svc.TransitRow(
                kind=svc.KIND_IN_REVIEW,
                qc_status="passed",
                ready_since=_WEDNESDAY,
                waiting_workdays=2,
                can_nudge=True,
                **base,
            )
        )
    )
    assert review.qc_status == "passed"
    assert review.ready_since == _WEDNESDAY
    assert review.waiting_workdays == 2
    assert review.can_nudge is True
    # Pozostałe rodzaje wierszy zostają przy wartościach domyślnych.
    sent = CvTransitRow(**asdict(svc.TransitRow(kind=svc.KIND_SENT, **base)))
    assert sent.qc_status is None and sent.ready_since is None
    assert sent.waiting_workdays == 0 and sent.can_nudge is False


def test_rejection_reason_comes_from_the_dictionary_or_the_note() -> None:
    assert (
        svc.rejection_reason_text("salary_mismatch", "cokolwiek")
        == "Rozbieżność oczekiwań finansowych"
    )
    assert (
        svc.rejection_reason_text(None, "Powód (rejected): stawka ponad budżet\nreszta")
        == "stawka ponad budżet"
    )
    # Zwykła notatka nie udaje powodu odrzucenia.
    assert svc.rejection_reason_text(None, "Zadzwonić w piątek") is None
    assert svc.rejection_reason_text(None, None) is None


# ── Integracyjne: prawdziwe ruchy i odczyt panelu ────────────────────────────


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


async def _transit(client: AsyncClient, headers: dict) -> dict | None:
    resp = await client.get("/api/board-tasks", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["cv_in_transit"]


def _mine(block: dict | None, group: str, candidate_id: int) -> list[dict]:
    assert block is not None
    return [r for r in block[group] if r["candidate_id"] == candidate_id]


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


async def _rejected_def_id(world: dict) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(PipelineStageDef.id).where(
                PipelineStageDef.template_id == world["template_id"],
                PipelineStageDef.is_terminal.is_(True),
            )
        )


async def _non_nordea_world(monkeypatch: pytest.MonkeyPatch):
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    other_id, other_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    async with AsyncSessionLocal() as db:
        (await db.get(Job, world["job_id"])).delivery_lead_id = dl_id
        await db.commit()
    return world, (rec_id, rec_creds), (other_id, other_creds), (dl_id, dl_creds)


@pytest.mark.asyncio
async def test_recruiter_follows_the_cv_from_review_to_the_client(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        world,
        (rec_id, rec_creds),
        (other_id, other_creds),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    other = await _login(api_client, other_creds)
    dl = await _login(api_client, dl_creds)
    cid = world["candidate_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        # Zweryfikowany to jeszcze praca rekrutera — nic nie jest „w drodze”.
        block = await _transit(api_client, rec)
        assert block is not None
        assert not any(_mine(block, g, cid) for g in ("returned", "in_review", "sent"))

        await _move(api_client, rec, world, "qc")
        review = _mine(await _transit(api_client, rec), "in_review", cid)
        assert [r["kind"] for r in review] == ["in_review"]
        assert review[0]["holder_name"].startswith("BT delivery_lead")
        assert review[0]["job_id"] == world["job_id"]
        # Inny rekruter nie widzi cudzego CV, a DL ma je w swoim przeglądzie.
        assert _mine(await _transit(api_client, other), "in_review", cid) == []
        dl_payload = (await api_client.get("/api/board-tasks", headers=dl)).json()
        assert [r["candidate_id"] for r in dl_payload["dl_review"]].count(cid) == 1
        assert _mine(dl_payload["cv_in_transit"], "in_review", cid) == []

        await _move(
            api_client,
            dl,
            world,
            "cv_sent",
            client_rate_value="170",
            client_rate_unit="hourly",
            client_rate_currency="PLN",
        )
        block = await _transit(api_client, rec)
        sent = _mine(block, "sent", cid)
        assert [r["kind"] for r in sent] == ["sent"]
        assert sent[0]["actor_name"].startswith("BT delivery_lead")
        assert _mine(block, "in_review", cid) == []
        assert block["sent_total"] >= 1
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_card_edited_by_the_delivery_lead_shows_who_and_what(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D4 (04.10.2026): DL poprawia kartę w przeglądzie, a rekruter widzi
    w „Twoje CV w drodze”, kto i które pola zmienił. Własne zapisy rekrutera
    nie są śladem."""
    (
        world,
        (rec_id, rec_creds),
        (other_id, _other_creds),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid, jid = world["candidate_id"], world["job_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        own = await api_client.put(
            "/api/recommendation-cards",
            headers=rec,
            json={"candidate_id": cid, "job_id": jid, "fields": {"english": "B2"}},
        )
        assert own.status_code == 200, own.text
        review = _mine(await _transit(api_client, rec), "in_review", cid)
        assert review[0]["card_edited_by"] is None

        edited = await api_client.put(
            "/api/recommendation-cards",
            headers=dl,
            json={
                "candidate_id": cid,
                "job_id": jid,
                "fields": {"motivation": "Chce wrócić do bankowości"},
            },
        )
        assert edited.status_code == 200, edited.text
        review = _mine(await _transit(api_client, rec), "in_review", cid)
        assert review[0]["card_edited_by"].startswith("BT delivery_lead")
        assert review[0]["card_edited_fields"] == ["Motywacja"]
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_rejection_by_the_delivery_lead_comes_back_with_the_reason(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        world,
        (rec_id, rec_creds),
        (other_id, _),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid = world["candidate_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        resp = await api_client.post(
            "/api/pipeline/move",
            headers=dl,
            json={
                "candidate_id": cid,
                "job_id": world["job_id"],
                "stage_def_id": await _rejected_def_id(world),
                "ended_by": "delivery_lead",
                "rejection_reason": "stawka ponad budżet",
            },
        )
        assert resp.status_code == 200, resp.text

        returned = _mine(await _transit(api_client, rec), "returned", cid)
        assert [r["kind"] for r in returned] == ["rejected_by_dl"]
        assert returned[0]["reason"] == "stawka ponad budżet"
        assert returned[0]["actor_name"].startswith("BT delivery_lead")
        # Odrzucenie to informacja, nie CV do poprawy (23.10.2026) — nie
        # liczy się do „Twój ruch” ani do sekcji porannego maila.
        transit = await _transit(api_client, rec)
        assert transit["returned_to_fix_total"] == transit["returned_total"] - 1
        # Delivery Lead nie dostaje wiadomości o własnej decyzji.
        assert _mine(await _transit(api_client, dl), "returned", cid) == []
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_card_sent_back_from_qc_disappears_after_the_next_move(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    (
        world,
        (rec_id, rec_creds),
        (other_id, _),
        (dl_id, dl_creds),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    cid = world["candidate_id"]
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        await _move(api_client, dl, world, "verified")

        returned = _mine(await _transit(api_client, rec), "returned", cid)
        assert [r["kind"] for r in returned] == ["sent_back"]
        assert returned[0]["actor_name"].startswith("BT delivery_lead")

        # Rekruter poprawia i przekazuje ponownie — wpis „wróciło” znika.
        await _move(api_client, rec, world, "qc")
        block = await _transit(api_client, rec)
        assert _mine(block, "returned", cid) == []
        assert [r["kind"] for r in _mine(block, "in_review", cid)] == ["in_review"]

        # Własne cofnięcie karty nie jest wiadomością.
        await _move(api_client, rec, world, "verified")
        assert _mine(await _transit(api_client, rec), "returned", cid) == []
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_nordea_cpro_queue_and_return(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    await seed_entry_row(world["candidate_id"], world["job_id"])
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    admin_id, admin_creds = await _seed_user(UserRole.admin)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    sender_id, sender_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    admin = await _login(api_client, admin_creds)
    rec = await _login(api_client, rec_creds)
    sender = await _login(api_client, sender_creds)
    dl = await _login(api_client, dl_creds)
    cid = world["candidate_id"]
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
            # Od 13.10.2026 „QC CV” u Nordei to przegląd DL (akceptacja do Cpro).
            review = _mine(await _transit(api_client, rec), "in_review", cid)
            assert [r["kind"] for r in review] == ["in_review"]

            await _move(api_client, dl, world, "cpro", **CPRO_RATE)
            review = _mine(await _transit(api_client, rec), "in_review", cid)
            assert [r["kind"] for r in review] == ["cpro_queue"]
            assert review[0]["holder_name"].startswith("BT recruiter")

            resp = await api_client.post(
                "/api/pipeline/move",
                headers=sender,
                json={
                    "candidate_id": cid,
                    "job_id": world["job_id"],
                    "stage_def_id": world["defs"]["qc"],
                    "notes": "Brak numeru projektu w CV",
                },
            )
            assert resp.status_code == 200, resp.text
            block = await _transit(api_client, rec)
            returned = _mine(block, "returned", cid)
            assert [r["kind"] for r in returned] == ["cpro_returned"]
            assert returned[0]["reason"] == "Brak numeru projektu w CV"
            assert _mine(block, "in_review", cid) == []
    finally:
        await _cleanup(world, [admin_id, rec_id, sender_id, dl_id])


@pytest.mark.asyncio
async def test_removed_from_the_dashboard_means_no_list_until_restored(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world, (rec_id, rec_creds), (other_id, _), (dl_id, _) = await _non_nordea_world(
        monkeypatch
    )
    rec = await _login(api_client, rec_creds)
    cid = world["candidate_id"]
    url = "/api/users/me/dashboard/panels/cv_in_transit"
    try:
        await _seed_screening(world, rec_id)
        await _move(api_client, rec, world, "verified")
        await _move(api_client, rec, world, "qc")
        assert _mine(await _transit(api_client, rec), "in_review", cid)

        hide = await api_client.put(url, headers=rec, json={"hidden": True})
        assert hide.status_code == 200, hide.text
        assert hide.json()["hidden_panels"] == ["cv_in_transit"]
        assert await _transit(api_client, rec) is None

        restore = await api_client.put(url, headers=rec, json={"hidden": False})
        assert restore.json()["hidden_panels"] == []
        assert _mine(await _transit(api_client, rec), "in_review", cid)
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_review_row_with_failing_qc_cannot_be_nudged(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """13.10.2026: karta stoi w „QC CV” 12 dni, ale QC jest do poprawy — ruch
    ma rekruter, więc lista nie daje mu „Przypomnij”."""
    (
        world,
        (rec_id, rec_creds),
        (other_id, _),
        (dl_id, _),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    cid = world["candidate_id"]
    now = datetime.now(timezone.utc)
    try:
        await _put_in_qc(world, moved_by=rec_id, moved_at=now - timedelta(days=12))
        await _add_qc_run(world, passed=False, created_at=now - timedelta(days=11))

        review = _mine(await _transit(api_client, rec), "in_review", cid)
        assert [r["kind"] for r in review] == ["in_review"]
        assert review[0]["qc_status"] == "failed"
        assert review[0]["ready_since"] is None
        assert review[0]["waiting_workdays"] == 0
        assert review[0]["can_nudge"] is False
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_review_row_ready_for_ten_days_can_be_nudged(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Czas czekania biegnie od zaliczenia QC, nie od wejścia do kolumny."""
    (
        world,
        (rec_id, rec_creds),
        (other_id, _),
        (dl_id, _),
    ) = await _non_nordea_world(monkeypatch)
    rec = await _login(api_client, rec_creds)
    cid = world["candidate_id"]
    now = datetime.now(timezone.utc).replace(microsecond=0)
    passed_at = now - timedelta(days=10)
    try:
        await _put_in_qc(world, moved_by=rec_id, moved_at=now - timedelta(days=12))
        await _add_qc_run(world, passed=False, created_at=now - timedelta(days=11))
        await _add_qc_run(world, passed=True, created_at=passed_at)

        review = _mine(await _transit(api_client, rec), "in_review", cid)
        assert review[0]["qc_status"] == "passed"
        assert datetime.fromisoformat(review[0]["ready_since"]) == passed_at
        assert review[0]["waiting_workdays"] >= dl_send_queue.LATE_WORKDAYS
        assert review[0]["can_nudge"] is True
        assert review[0]["holder_name"].startswith("BT delivery_lead")
    finally:
        await _cleanup(world, [rec_id, other_id, dl_id])


@pytest.mark.asyncio
async def test_review_without_a_job_lead_names_the_client_portfolio(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rekrutacja bez Delivery Leada: przegląd idzie do DL-i z portfelem
    klienta (`stage_handoff_recipients._dl_reviewers`), a lista do 13.10.2026
    pokazywała wtedy „Delivery Lead klienta” zamiast osoby."""
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    first_id, _ = await _seed_user(UserRole.delivery_lead)
    second_id, _ = await _seed_user(UserRole.delivery_lead)
    # Rekruter z klientem w portfelu nie jest Delivery Leadem — nie przegląda.
    not_dl_id, _ = await _seed_user(UserRole.recruiter)
    rec = await _login(api_client, rec_creds)
    cid, client_id = world["candidate_id"], world["client_id"]

    async def assign(user_id: int) -> None:
        async with AsyncSessionLocal() as db:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=user_id, client_id=client_id
                )
            )
            await db.commit()

    try:
        await _put_in_qc(
            world,
            moved_by=rec_id,
            moved_at=datetime.now(timezone.utc) - timedelta(hours=3),
        )
        review = _mine(await _transit(api_client, rec), "in_review", cid)
        assert review[0]["holder_name"] is None

        await assign(first_id)
        await assign(not_dl_id)
        review = _mine(await _transit(api_client, rec), "in_review", cid)
        holder = review[0]["holder_name"]
        assert holder.startswith("BT delivery_lead") and "+" not in holder

        await assign(second_id)
        review = _mine(await _transit(api_client, rec), "in_review", cid)
        holder = review[0]["holder_name"]
        assert holder.startswith("BT delivery_lead") and holder.endswith(" +1")
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(DeliveryLeadClientAssignment).where(
                    DeliveryLeadClientAssignment.client_id == client_id
                )
            )
            await db.commit()
        await _cleanup(world, [rec_id, first_id, second_id, not_dl_id])
