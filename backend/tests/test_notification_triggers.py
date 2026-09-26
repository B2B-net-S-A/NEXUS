"""Smoke tests for `app.services.notification_triggers`.

Pełne integration testy (z seedem kandydatów / calli / interview) wymagają
działającego kontenera postgres + wykonanej migracji 0029. Te testy weryfikują
sam interfejs: importy, sygnatury, domyślny empty-DB path (zero alertów).

W pełnym QA uruchamiaj przez `POST /api/admin/notifications/trigger-check` na
seedowanej bazie (patrz docs/phase13-notifications).
"""

from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.services import notification_triggers as nt


def test_exports_the_core_triggers():
    names = {
        "check_dl_stage_stale_6h",
        "check_client_feedback_eobd",
        "check_candidate_feedback_1h",
        "check_stage_stuck_7d",
    }
    for name in names:
        fn = getattr(nt, name)
        assert inspect.iscoroutinefunction(fn), f"{name} musi być async"


def test_run_all_triggers_keys():
    assert inspect.iscoroutinefunction(nt.run_all_triggers)
    sig = inspect.signature(nt.run_all_triggers)
    assert list(sig.parameters.keys()) == ["db", "now"]


def test_emit_signature_is_keyword_only_after_db():
    sig = inspect.signature(nt.emit)
    params = sig.parameters
    # user_id, title, message, ntype, ... są keyword-only (po `*, ` w sygnaturze).
    assert params["user_id"].kind == inspect.Parameter.KEYWORD_ONLY
    assert params["ntype"].kind == inspect.Parameter.KEYWORD_ONLY
    assert params["related_entity_id"].kind == inspect.Parameter.KEYWORD_ONLY


@pytest_asyncio.fixture
async def empty_db():
    """Connect to the test DB via AsyncSessionLocal (requires DATABASE_URL + migrations)."""
    pytest.importorskip("asyncpg")
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            yield db
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB unavailable for integration test: {exc}")


async def test_all_triggers_return_zero_when_no_data(empty_db):
    """Gdy baza pusta (lub bez pasujących rekordów), każdy trigger emituje 0."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    # Wtorek 21:00 Warsaw — poza oknami KPI/EOBD; stress testuje same queries.
    now = datetime(2026, 4, 21, 21, 0, tzinfo=ZoneInfo("Europe/Warsaw"))
    results = await nt.run_all_triggers(empty_db, now)
    # Nie zakładamy że baza jest pusta (test może lecieć na shared instance),
    # ale zwrócony słownik musi mieć wszystkie 8 kluczy z int values.
    assert set(results.keys()) == {
        "dl_stage_stale_6h",
        "stage_stuck_7d",
        "candidate_feedback_1h",
        "client_feedback_eobd",
        "post_interview_t15",
        "post_interview_t45",
        "post_interview_t2h_escalation",
        "board_tasks_digest",
        "prep_attention",
    }
    assert all(isinstance(v, int) and v >= 0 for v in results.values())
    # Time-gated trigger musi zwrócić 0 o 21:00.
    assert results["client_feedback_eobd"] == 0


# ── stage_stuck_7d (audyt 17.09.2026) ─────────────────────────────────────────
#
# Do 09.2026 trigger nie miał dolnej granicy wieku ani filtra otwartych
# rekrutacji, a dedup był dobowy — każdy zaległy kandydat dawał nowy wiersz
# każdego dnia. Testy przekazują własną mapę `latest`, żeby nie skanować (i nie
# powiadamiać) całej współdzielonej bazy testowej.

# Środa; tydzień ISO zaczyna się w poniedziałek 2035-06-04 (Europe/Warsaw).
_STUCK_NOW = datetime(2035, 6, 6, 10, 0, tzinfo=timezone.utc)


async def _seed_stuck_world(*, job_status, days_ago: float) -> dict:
    import uuid

    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.user import User, UserRole

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"stuck-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!PassX"),
            name=f"Stuck Recruiter {tag}",
            role=UserRole.recruiter,
            is_active=True,
        )
        candidate = Candidate(
            name="Anna",
            lastname=f"Utknięta-{tag}",
            email=f"stuck-cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        client = Client(name=f"StuckClient-{tag}")
        db.add_all([recruiter, candidate, client])
        await db.flush()
        job = Job(
            title=f"Rekrutacja-{tag}",
            client_id=client.id,
            status=job_status,
            recruiter_id=recruiter.id,
        )
        db.add(job)
        await db.flush()
        stage = CandidateStage(
            candidate_id=candidate.id,
            job_id=job.id,
            stage=PipelineStage.cv_sent,
            moved_at=_STUCK_NOW - timedelta(days=days_ago),
        )
        db.add(stage)
        await db.commit()
        return {
            "recruiter_id": recruiter.id,
            "candidate_id": candidate.id,
            "job_id": job.id,
            "stage_id": stage.id,
            "stage": nt.LatestStage(
                id=stage.id,
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.cv_sent,
                moved_at=stage.moved_at,
            ),
            "tag": tag,
        }


async def _run_stuck(world: dict, now: datetime = _STUCK_NOW) -> int:
    from app.core.database import AsyncSessionLocal

    latest = {(world["candidate_id"], world["job_id"]): world["stage"]}
    async with AsyncSessionLocal() as db:
        emitted = await nt.check_stage_stuck_7d(db, now, latest)
        await db.commit()
    return emitted


async def _stuck_rows(world: dict) -> list:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.notification import Notification, NotificationType

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(Notification).where(
                Notification.notification_type == NotificationType.stage_stuck_7d,
                Notification.related_entity_id == world["stage_id"],
            )
        )
        return list(rows.scalars().all())


async def _db_or_skip():
    pytest.importorskip("asyncpg")
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"DB unavailable for integration test: {exc}")


async def test_stage_stuck_skips_closed_recruitment():
    from app.models.job import JobStatus

    await _db_or_skip()
    world = await _seed_stuck_world(job_status=JobStatus.closed, days_ago=10)
    assert await _run_stuck(world) == 0
    assert await _stuck_rows(world) == []


async def test_stage_stuck_skips_stage_older_than_max_days():
    from app.models.job import JobStatus

    await _db_or_skip()
    world = await _seed_stuck_world(job_status=JobStatus.published, days_ago=400)
    assert await _run_stuck(world) == 0
    assert await _stuck_rows(world) == []


async def test_stage_stuck_open_recruitment_emits_readable_reminder_once_per_week():
    from sqlalchemy import update

    from app.core.database import AsyncSessionLocal
    from app.models.job import JobStatus
    from app.models.notification import Notification

    await _db_or_skip()
    world = await _seed_stuck_world(job_status=JobStatus.published, days_ago=10)
    assert await _run_stuck(world) == 1
    rows = await _stuck_rows(world)
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == world["recruiter_id"]
    assert f"Anna Utknięta-{world['tag']}" in row.message
    assert "od 10 dni" in row.message
    assert "„CV Wysłane”" in row.message
    assert f"w rekrutacji „Rekrutacja-{world['tag']}”" in row.message
    assert "#" not in row.message and "cv_sent" not in row.message
    assert "ofercie" not in row.message
    assert row.link == f"/jobs/{world['job_id']}?candidate={world['candidate_id']}"

    # Wiersz z poniedziałku TEGO tygodnia (inny dzień niż dzisiejszy wiersz
    # z bazy, więc indeks dobowy tu nie pomaga) — kolejny bieg nic nie dodaje.
    monday = datetime(2035, 6, 4, 8, 0, tzinfo=timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Notification)
            .where(Notification.id == row.id)
            .values(created_at=monday)
        )
        await db.commit()
    assert await _run_stuck(world) == 0
    assert len(await _stuck_rows(world)) == 1

    # Wiersz z poprzedniego tygodnia nie blokuje przypomnienia w nowym.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Notification)
            .where(Notification.id == row.id)
            .values(created_at=monday - timedelta(days=1))
        )
        await db.commit()
    assert await _run_stuck(world) == 1
    assert len(await _stuck_rows(world)) == 2


def test_warsaw_week_start_is_monday_midnight_local():
    # Niedziela 23:30 UTC = poniedziałek 01:30 w Warszawie → już nowy tydzień.
    now = datetime(2035, 6, 10, 23, 30, tzinfo=timezone.utc)
    assert nt._warsaw_week_start_utc(now) == datetime(
        2035, 6, 10, 22, 0, tzinfo=timezone.utc
    )


# ── Linki powiadomień otwierają kartę kandydata (17.09.2026) ─────────────────


class _Captured:
    def __init__(self) -> None:
        self.links: list[str | None] = []

    async def emit(self, db, **kwargs):
        self.links.append(kwargs.get("link"))
        return object()


@pytest.mark.asyncio
async def test_dl_stage_stale_link_opens_the_candidate_on_the_board(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.models.recruitment_pipeline import PipelineStage

    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    stage = nt.LatestStage(
        id=5,
        candidate_id=77,
        job_id=12,
        stage=PipelineStage.cv_sent,
        moved_at=now - timedelta(hours=8),
    )
    captured = _Captured()

    async def jobs_by_id(db, ids):  # lustro `_open_jobs_by_id` (#1593)
        return {12: SimpleNamespace(id=12, title="Java")}

    async def targets(db, job):
        return [3]

    monkeypatch.setattr(nt, "_open_jobs_by_id", jobs_by_id)
    monkeypatch.setattr(nt, "_delivery_lead_targets", targets)
    monkeypatch.setattr(nt, "emit", captured.emit)

    assert await nt.check_dl_stage_stale_6h(None, now, {(77, 12): stage}) == 1
    assert captured.links == ["/jobs/12?candidate=77"]


@pytest.mark.asyncio
async def test_client_feedback_link_opens_the_candidate_on_the_board(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from app.models.recruitment_pipeline import PipelineStage

    now = datetime(2026, 9, 17, 14, 30, tzinfo=timezone.utc)
    event = SimpleNamespace(
        id=9,
        candidate_id=77,
        job_id=12,
        start_time=now - timedelta(hours=3),
        end_time=now - timedelta(hours=2),
    )

    class _Rows:
        def __init__(self, items=None, scalar=None):
            self._items, self._scalar = items, scalar

        def scalars(self):
            return SimpleNamespace(all=lambda: list(self._items))

        def scalar(self):
            return self._scalar

    class _Db:
        def __init__(self):
            self.calls = 0

        async def execute(self, statement):
            self.calls += 1
            return _Rows(items=[event]) if self.calls == 1 else _Rows(scalar=0)

    latest = {
        (77, 12): nt.LatestStage(
            id=5,
            candidate_id=77,
            job_id=12,
            stage=PipelineStage.client_interview,
            moved_at=now - timedelta(days=1),
        )
    }
    captured = _Captured()

    async def jobs_by_id(db, ids):  # lustro `_open_jobs_by_id` (#1593)
        return {12: SimpleNamespace(id=12, title="Java")}

    async def targets(db, job):
        return [3]

    monkeypatch.setattr(nt, "is_within_window", lambda *a, **k: True)
    monkeypatch.setattr(nt, "_open_jobs_by_id", jobs_by_id)
    monkeypatch.setattr(nt, "_delivery_lead_targets", targets)
    monkeypatch.setattr(nt, "emit", captured.emit)

    assert await nt.check_client_feedback_eobd(_Db(), now, latest) == 1
    assert captured.links == ["/jobs/12?candidate=77"]


# ── Nieaktywne konto = brak osoby (runda 6 audytu) ───────────────────────────


def _active_only(*active_ids):
    async def is_active(db, user_id):
        return user_id in active_ids

    return is_active


@pytest.mark.asyncio
async def test_post_interview_call_skips_inactive_owner_for_the_job_recruiter(
    monkeypatch,
):
    from types import SimpleNamespace

    from app.models.calendar_event import CalendarEvent, EventType

    ev = CalendarEvent(
        event_type=EventType.client_interview, operational_owner_id=11, created_by=11
    )
    job = SimpleNamespace(id=1, recruiter_id=33, delivery_lead_id=44)
    monkeypatch.setattr(nt, "_user_is_active", _active_only(33))
    assert await nt._post_interview_recipients(None, ev, job, client_side=False) == [33]

    # Nikt aktywny z rekrutacji → zapas DL-owy (DL albo HoR).
    async def targets(db, job):
        return [90]

    monkeypatch.setattr(nt, "_user_is_active", _active_only())
    monkeypatch.setattr(nt, "_delivery_lead_targets", targets)
    assert await nt._post_interview_recipients(None, ev, job, client_side=False) == [90]


@pytest.mark.asyncio
async def test_post_interview_call_goes_to_the_compass_substitute(monkeypatch):
    from types import SimpleNamespace

    from app.models.calendar_event import CalendarEvent, EventType
    from app.services import workforce_availability

    async def substitute(db, owner_id):
        return 77 if owner_id == 33 else owner_id

    monkeypatch.setattr(workforce_availability, "effective_owner_id", substitute)
    monkeypatch.setattr(nt, "_user_is_active", _active_only(77))
    ev = CalendarEvent(event_type=EventType.interview, created_by=33)
    job = SimpleNamespace(id=1, recruiter_id=33, delivery_lead_id=None)
    assert await nt._post_interview_recipients(None, ev, job, client_side=False) == [77]


@pytest.mark.asyncio
async def test_stage_stuck_reminder_for_inactive_recruiter_goes_to_the_dl(
    monkeypatch,
):
    from types import SimpleNamespace

    from app.models.recruitment_pipeline import PipelineStage

    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    stage = nt.LatestStage(
        id=5,
        candidate_id=77,
        job_id=12,
        stage=PipelineStage.cv_sent,
        moved_at=now - timedelta(days=10),
    )
    sent: list[int] = []

    async def emit(db, **kwargs):
        sent.append(kwargs["user_id"])
        return object()

    async def jobs_by_id(db, ids):
        return {
            12: SimpleNamespace(id=12, title="Java", working_title=None, recruiter_id=3)
        }

    async def targets(db, job):
        return [44]

    async def names(db, ids):
        return {77: "Anna Nowak"}

    class _Db:
        async def execute(self, statement):
            return []

    monkeypatch.setattr(nt, "_open_jobs_by_id", jobs_by_id)
    monkeypatch.setattr(nt, "_delivery_lead_targets", targets)
    monkeypatch.setattr(nt, "_candidate_names", names)
    monkeypatch.setattr(nt, "_user_is_active", _active_only())
    monkeypatch.setattr(nt, "emit", emit)
    assert await nt.check_stage_stuck_7d(_Db(), now, {(77, 12): stage}) == 1
    assert sent == [44]
