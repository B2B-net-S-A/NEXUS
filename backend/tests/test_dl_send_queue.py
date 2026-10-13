"""„Do wysłania do klienta” — jedna reguła kolejki Delivery Leada (13.10.2026).

Pierwsza część nie potrzebuje bazy (dni robocze, pilność, gotowość, czyj
przegląd). Druga sprawdza zapytanie: brak okna czasu, zakres patrzącego,
klient z kolejką Cpro, wiersz z importu Traffita i trasę górnego paska.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, update

from app.core.database import AsyncSessionLocal
from app.models.cv_qc_run import CvQcRun
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services import board_tasks as svc
from app.services import dl_send_queue as queue
from tests.test_board_tasks import _cleanup, _login, _seed_user, _seed_world

UTC = timezone.utc


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


def _task(**kw) -> svc.BoardTask:
    base = dict(
        kind=svc.KIND_DL_REVIEW,
        stage_id=1,
        candidate_id=1,
        candidate_name="Kandydat Testowy",
        job_id=1,
        job_title="Rekrutacja testowa",
        client_id=7,
        client_name="Klient testowy",
        since=datetime(2026, 3, 2, 10, 0, tzinfo=UTC),
        process_state_version=0,
        target_stage_def_id=None,
    )
    base.update(kw)
    return svc.BoardTask(**base)


def _user(uid: int, *roles: UserRole) -> SimpleNamespace:
    return SimpleNamespace(id=uid, has_role=lambda role: role in roles)


# ── Bez bazy ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("ready_since", "today", "expected"),
    [
        # Dzień gotowości się nie liczy.
        (datetime(2026, 3, 4, 9, 0, tzinfo=UTC), date(2026, 3, 4), 0),
        (datetime(2026, 3, 4, 9, 0, tzinfo=UTC), date(2026, 3, 5), 1),
        (datetime(2026, 3, 4, 9, 0, tzinfo=UTC), date(2026, 3, 6), 2),
        # Piątek → sobota i niedziela nie są dniami roboczymi, poniedziałek jest.
        (datetime(2026, 3, 6, 15, 0, tzinfo=UTC), date(2026, 3, 8), 0),
        (datetime(2026, 3, 6, 15, 0, tzinfo=UTC), date(2026, 3, 9), 1),
        # 11 listopada (środa) to święto: wtorek → czwartek = jeden dzień roboczy.
        (datetime(2026, 11, 10, 9, 0, tzinfo=UTC), date(2026, 11, 12), 1),
        # 22:30 UTC w październiku to już następny dzień w Warszawie.
        (datetime(2026, 10, 12, 22, 30, tzinfo=UTC), date(2026, 10, 13), 0),
    ],
)
def test_waiting_workdays_count_from_the_day_after_readiness(
    ready_since: datetime, today: date, expected: int
) -> None:
    assert queue.waiting_workdays(ready_since, today) == expected


def test_urgency_thresholds() -> None:
    assert queue.urgency_for(0) == queue.URGENCY_FRESH
    assert queue.urgency_for(queue.DUE_WORKDAYS) == queue.URGENCY_DUE
    assert queue.urgency_for(queue.LATE_WORKDAYS) == queue.URGENCY_LATE
    assert queue.urgency_for(9) == queue.URGENCY_LATE


@pytest.mark.parametrize("status", ["failed", "unchecked"])
def test_card_with_open_qc_is_not_the_delivery_leads_move(status: str) -> None:
    task = _task(qc_status=status)
    queue.apply_readiness(task, ok_at=None, today=date(2026, 3, 20))
    assert task.ready is False
    assert task.ready_since is None
    assert task.urgency is None
    assert task.waiting_workdays == 0
    assert queue.counts_for_reviewer(task) is False


def test_waiting_starts_when_qc_passed_not_when_the_card_entered_the_column() -> None:
    """Karta weszła w poniedziałek, rekruter poprawiał CV do środy — Delivery
    Lead czeka od środy, nie od poniedziałku."""

    task = _task(qc_status="passed")
    queue.apply_readiness(
        task,
        ok_at=datetime(2026, 3, 4, 9, 0, tzinfo=UTC),
        today=date(2026, 3, 6),
    )
    assert task.ready is True
    assert task.ready_since == datetime(2026, 3, 4, 9, 0, tzinfo=UTC)
    assert task.waiting_workdays == 2
    assert task.urgency == queue.URGENCY_LATE


def test_qc_passed_before_the_move_counts_from_the_move() -> None:
    task = _task(qc_status="overridden")
    queue.apply_readiness(
        task,
        ok_at=datetime(2026, 2, 27, 9, 0, tzinfo=UTC),
        today=date(2026, 3, 3),
    )
    assert task.ready is True
    assert task.ready_since == task.since
    assert task.waiting_workdays == 1
    assert task.urgency == queue.URGENCY_DUE


def test_imported_card_does_not_wake_counters_even_when_ready() -> None:
    task = _task(qc_status="passed", imported=True)
    queue.apply_readiness(task, ok_at=None, today=date(2026, 3, 3))
    assert task.ready is True
    assert queue.counts_for_reviewer(task) is False


def test_worst_urgency_of_a_list() -> None:
    fresh = _task(urgency=queue.URGENCY_FRESH)
    due = _task(urgency=queue.URGENCY_DUE)
    late = _task(urgency=queue.URGENCY_LATE)
    assert queue.worst_urgency([]) is None
    assert queue.worst_urgency([_task()]) is None
    assert queue.worst_urgency([fresh, due]) == queue.URGENCY_DUE
    assert queue.worst_urgency([late, fresh, due]) == queue.URGENCY_LATE


def test_review_belongs_to_the_job_lead_then_to_the_client_portfolio() -> None:
    lead = _user(5, UserRole.delivery_lead)
    other = _user(6, UserRole.delivery_lead)
    admin = _user(1, UserRole.admin)
    portfolio = frozenset({7})
    # Delivery Lead rekrutacji wygrywa z portfelem.
    assert svc.reviews_as_dl(lead, delivery_lead_id=5, client_id=7, portfolio=frozenset())
    assert not svc.reviews_as_dl(other, delivery_lead_id=5, client_id=7, portfolio=portfolio)
    # Bez DL-a w rekrutacji (albo z nieaktywnym kontem) — portfel klienta.
    assert svc.reviews_as_dl(other, delivery_lead_id=None, client_id=7, portfolio=portfolio)
    assert not svc.reviews_as_dl(lead, delivery_lead_id=None, client_id=7, portfolio=frozenset())
    assert not svc.reviews_as_dl(other, delivery_lead_id=None, client_id=None, portfolio=portfolio)
    # Admin bez roli Delivery Leada nie ma przeglądu.
    assert not svc.reviews_as_dl(admin, delivery_lead_id=1, client_id=7, portfolio=portfolio)


def test_row_dict_carries_the_send_queue_fields() -> None:
    row = _task(qc_status="passed", handed_over_by_name="Rekruter Testowy").as_dict()
    for key in (
        "ready",
        "ready_since",
        "waiting_workdays",
        "urgency",
        "imported",
        "handed_over_by_name",
        "budget_min_hourly",
        "budget_max_hourly",
        "deadline",
    ):
        assert key in row
    assert row["handed_over_by_name"] == "Rekruter Testowy"


# ── Z bazą ──────────────────────────────────────────────────────────────────


async def _put_in_qc(
    world: dict,
    *,
    moved_by: int | None,
    moved_at: datetime,
    external_source: str | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        row = CandidateStage(
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            stage="interview",
            stage_def_id=world["defs"]["qc"],
            moved_by=moved_by,
            moved_at=moved_at,
            external_source=external_source,
        )
        db.add(row)
        await db.commit()
        return row.id


async def _add_qc_run(
    world: dict, *, passed: bool, created_at: datetime, override: str | None = None
) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CvQcRun(
                candidate_id=world["candidate_id"],
                job_id=world["job_id"],
                passed=passed,
                blocking_failed=0 if passed else 2,
                warnings_count=0,
                result={},
                override_reason=override,
                created_at=created_at,
            )
        )
        await db.commit()


async def _set_job_lead(world: dict, user_id: int | None) -> None:
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.delivery_lead_id = user_id
        await db.commit()


async def _rows_for_pair(world: dict, *, now: datetime) -> list[svc.BoardTask]:
    async with AsyncSessionLocal() as db:
        return await queue.load_rows(
            db,
            scope=queue.Scope(pair=(world["candidate_id"], world["job_id"])),
            now=now,
        )


@pytest.mark.asyncio
async def test_queue_has_no_time_window_and_counts_from_readiness(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Karta sprzed 45 dni dalej jest w kolejce; dopóki QC nie przeszło, jest
    „jeszcze u rekrutera”, a po zaliczeniu czas liczy się od zaliczenia."""

    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    other_id, other_creds = await _seed_user(UserRole.delivery_lead)
    rec = await _login(api_client, rec_creds)
    dl = await _login(api_client, dl_creds)
    other = await _login(api_client, other_creds)
    cid = world["candidate_id"]
    await _set_job_lead(world, dl_id)
    entered = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
    try:
        stage_id = await _put_in_qc(world, moved_by=rec_id, moved_at=entered)
        friday = datetime(2026, 3, 6, 12, 0, tzinfo=UTC)

        # Bez przebiegu QC: wiersz jest, ale ruch ma rekruter.
        rows = await _rows_for_pair(world, now=friday)
        assert [t.stage_id for t in rows] == [stage_id]
        assert rows[0].qc_status == "unchecked"
        assert rows[0].ready is False
        assert rows[0].imported is False

        # QC do poprawy — dalej nie jest gotowe.
        await _add_qc_run(
            world, passed=False, created_at=datetime(2026, 3, 3, 9, 0, tzinfo=UTC)
        )
        rows = await _rows_for_pair(world, now=friday)
        assert rows[0].qc_status == "failed"
        assert rows[0].ready is False

        # W środę QC przechodzi — Delivery Lead czeka od środy.
        passed_at = datetime(2026, 3, 4, 9, 0, tzinfo=UTC)
        await _add_qc_run(world, passed=True, created_at=passed_at)
        rows = await _rows_for_pair(world, now=friday)
        assert rows[0].ready is True
        assert rows[0].ready_since == passed_at
        assert rows[0].waiting_workdays == 2
        assert rows[0].urgency == queue.URGENCY_LATE

        # Trasa górnego paska: tylko Delivery Lead tej rekrutacji.
        mine = (await api_client.get("/api/board-tasks/dl-send", headers=dl)).json()
        assert mine["ready_total"] >= 1
        row = next(r for r in mine["ready"] if r["candidate_id"] == cid)
        assert row["stage_id"] == stage_id
        assert row["urgency"] == queue.URGENCY_LATE
        assert row["handed_over_by_name"].startswith("BT recruiter")
        assert mine["worst_urgency"] == queue.URGENCY_LATE
        for headers in (rec, other):
            body = (
                await api_client.get("/api/board-tasks/dl-send", headers=headers)
            ).json()
            assert all(r["candidate_id"] != cid for r in body["ready"])
        empty = (await api_client.get("/api/board-tasks/dl-send", headers=rec)).json()
        assert empty == {
            "ready": [],
            "ready_total": 0,
            "not_ready_total": 0,
            "imported_total": 0,
            "worst_urgency": None,
        }

        # Pulpit dostaje ten sam wiersz z polami kolejki — także po 45 dniach.
        board = (await api_client.get("/api/board-tasks", headers=dl)).json()
        dashboard = [r for r in board["dl_review"] if r["candidate_id"] == cid]
        assert len(dashboard) == 1
        assert dashboard[0]["ready"] is True
        assert dashboard[0]["handed_over_by_name"].startswith("BT recruiter")
        assert dashboard[0]["imported"] is False
    finally:
        await _cleanup(world, [rec_id, dl_id, other_id])


@pytest.mark.asyncio
async def test_viewer_scope_is_the_job_lead_then_the_client_portfolio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Zakres w SQL = `reviews_as_dl`: DL rekrutacji wygrywa; bez niego (albo
    z nieaktywnym kontem) przegląd idzie do portfela klienta."""

    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    portfolio_id, _ = await _seed_user(UserRole.delivery_lead)
    job_lead_id, _ = await _seed_user(UserRole.delivery_lead)
    gone_id, _ = await _seed_user(UserRole.delivery_lead)
    recruiter_id, _ = await _seed_user(UserRole.recruiter)
    now = datetime.now(UTC)
    client_id = world["client_id"]

    async def seen_by(user_id: int) -> list[int]:
        async with AsyncSessionLocal() as db:
            user = await db.get(User, user_id)
            portfolio = await svc.dl_portfolio_client_ids(db, user_id)
            rows = await queue.load_for_viewer(db, user, portfolio=portfolio, now=now)
            return [t.candidate_id for t in rows if t.job_id == world["job_id"]]

    try:
        async with AsyncSessionLocal() as db:
            db.add(
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=portfolio_id, client_id=client_id
                )
            )
            await db.execute(
                update(User).where(User.id == gone_id).values(is_active=False)
            )
            await db.commit()
        await _put_in_qc(world, moved_by=None, moved_at=now - timedelta(hours=3))
        cid = world["candidate_id"]

        # Rekrutacja bez DL-a: portfel klienta.
        assert await seen_by(portfolio_id) == [cid]
        assert await seen_by(job_lead_id) == []
        # Rekruter z portfelem nie istnieje — brak roli = pusto bez zapytań.
        assert await seen_by(recruiter_id) == []

        # Nieaktywny DL w rekrutacji = jak brak DL-a.
        await _set_job_lead(world, gone_id)
        assert await seen_by(portfolio_id) == [cid]

        # Aktywny DL rekrutacji wygrywa z portfelem.
        await _set_job_lead(world, job_lead_id)
        assert await seen_by(job_lead_id) == [cid]
        assert await seen_by(portfolio_id) == []
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(DeliveryLeadClientAssignment).where(
                    DeliveryLeadClientAssignment.client_id == client_id
                )
            )
            await db.commit()
        await _cleanup(world, [portfolio_id, job_lead_id, gone_id, recruiter_id])


@pytest.mark.asyncio
async def test_cpro_client_is_skipped_and_traffit_row_is_marked_imported(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    dl = await _login(api_client, dl_creds)
    cid = world["candidate_id"]
    await _set_job_lead(world, dl_id)
    now = datetime.now(UTC)
    try:
        await _put_in_qc(
            world,
            moved_by=None,
            moved_at=now - timedelta(days=3),
            external_source="traffit",
        )
        await _add_qc_run(world, passed=True, created_at=now - timedelta(days=2))

        # U klienta z kolejką Cpro przeglądu DL nie ma.
        monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
        assert await _rows_for_pair(world, now=now) == []

        # Poza nim: wiersz z importu jest w kolejce, ale nie budzi licznika.
        monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
        rows = await _rows_for_pair(world, now=now)
        assert len(rows) == 1
        assert rows[0].imported is True
        assert rows[0].ready is True
        assert queue.counts_for_reviewer(rows[0]) is False
        body = (await api_client.get("/api/board-tasks/dl-send", headers=dl)).json()
        assert all(r["candidate_id"] != cid for r in body["ready"])
        assert body["imported_total"] >= 1
    finally:
        await _cleanup(world, [dl_id])
