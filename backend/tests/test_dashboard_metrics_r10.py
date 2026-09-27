"""Kreator metryk pulpitu — poprawki rundy 10 audytu (R10-N1-*).

- N1-1: kafelki z kredytem „Moje KPI" liczą JEDNĄ migawkę całej firmy
  (nie `VERIFIER_ANCHORED_CTE` na osobę i drugi raz dla porównania);
- N1-3: „moje rekrutacje" = ta sama reguła co „Moje" na `/jobs`
  (współpracownicy i żywe przypisania);
- N1-5: PUT pulpitu z 41 kafelkami albo powtórzonym id = 422, nie 500;
- N1-6: id spoza int4 w filtrach = 422, nie DataError;
- N1-7: pusty zespół = 0 z notą, nie dane samego użytkownika;
- N1-9: „otwarte teraz" = pigułka „Otwarte" rejestru (bez zamkniętych,
  ze szkicami, bez klientów ukrytych i usuniętych).
"""

from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)

TODAY = date(2026, 9, 27)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def scalar(self):
        return 0


class _FakeDb:
    """Liczy wykonania pełnego CTE kredytu i oddaje przygotowane wiersze."""

    def __init__(self, rows):
        self.rows = rows
        self.statements: list[str] = []

    async def execute(self, stmt, params=None):
        self.statements.append(str(stmt))
        return _Result(self.rows if "classified_stage_ranked" in str(stmt) else [])

    @property
    def cte_runs(self) -> int:
        return sum("classified_stage_ranked" in s for s in self.statements)


def _definition(**over):
    from app.services.custom_metrics.definition import MetricDefinition

    body = {
        "source": "pipeline_moves",
        "measure": "first_reach",
        "stage": "cv_sent",
        "filters": {"author": "me"},
        "group_by": "none",
        "period": "last_30_days",
    }
    body.update(over)
    return MetricDefinition.model_validate(body)


def _scope(kind="self", operators=frozenset()):
    from app.services.access_scope import DashboardScope, ScopeKind

    return DashboardScope(
        kind=ScopeKind(kind), user_id=7, allowed_operator_user_ids=operators
    )


def _rows():
    # (credit_user, stage, job_id, client_id, competence_category_id, dzień, n)
    d = TODAY - timedelta(days=3)
    prev = TODAY - timedelta(days=40)
    return [
        (7, "cv_sent", 1, 10, 100, d, 2),
        (7, "cv_sent", 2, 11, 101, d - timedelta(days=1), 1),
        (7, "verified", 1, 10, 100, d, 5),  # inny etap
        (8, "cv_sent", 1, 10, 100, d, 4),  # inna osoba
        (7, "cv_sent", 1, 10, 100, prev, 3),  # poprzedni okres
        (7, "cv_sent", 1, 10, 100, TODAY - timedelta(days=400), 9),  # poza oknami
        (None, "cv_sent", 3, 10, 100, d, 6),  # kamień bez autora
    ]


@pytest.fixture(autouse=True)
def _allow_sources(monkeypatch):
    from app.services.custom_metrics import engine

    monkeypatch.setattr(engine, "source_denial", lambda user, source: None)


async def _clear_snapshot():
    from app.core.cache import cache_invalidate
    from app.services.custom_metrics import engine

    await cache_invalidate(engine._CREDITED_KEY_PREFIX)


# ── N1-1 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_compare_previous_runs_the_credit_cte_once():
    from app.services.custom_metrics.engine import evaluate_metric

    await _clear_snapshot()
    db = _FakeDb(_rows())
    result = await evaluate_metric(
        db,
        SimpleNamespace(id=7),
        _definition(compare_previous=True),
        today=TODAY,
        scope=_scope(),
    )
    assert db.cte_runs == 1, db.statements
    assert result.value == 3.0  # 2 + 1 w oknie, bez innego etapu i osoby
    assert result.previous_value == 3.0


@pytest.mark.asyncio
async def test_second_person_reads_the_same_company_snapshot(monkeypatch):
    from app.services.custom_metrics import engine

    monkeypatch.setattr(engine, "_CREDITED_SNAPSHOT_TTL_SECONDS", 60)
    await _clear_snapshot()
    db = _FakeDb(_rows())
    first = await engine.evaluate_metric(
        db, SimpleNamespace(id=7), _definition(), today=TODAY, scope=_scope()
    )
    second = await engine.evaluate_metric(
        db, SimpleNamespace(id=8), _definition(), today=TODAY, scope=_scope()
    )
    await _clear_snapshot()
    assert db.cte_runs == 1, db.statements
    assert first.value == 3.0
    assert second.value == 4.0


@pytest.mark.asyncio
async def test_snapshot_filters_and_groups_like_the_sql_did():
    from app.services.custom_metrics.engine import evaluate_metric

    await _clear_snapshot()
    by_client = await evaluate_metric(
        _FakeDb(_rows()),
        SimpleNamespace(id=7),
        _definition(group_by="client", filters={"author": "me", "client_ids": [10]}),
        today=TODAY,
        scope=_scope(),
    )
    assert by_client.value == 2.0
    assert [s["key"] for s in by_client.series] == ["10"]

    by_person = await evaluate_metric(
        _FakeDb(_rows()),
        SimpleNamespace(id=7),
        _definition(group_by="recruiter", filters={"author": "all"}),
        today=TODAY,
        scope=_scope("organization"),
    )
    values = {s["key"]: s["value"] for s in by_person.series}
    assert values["7"] == 3.0 and values["8"] == 4.0
    assert values["unassigned"] == 6.0
    assert by_person.value == 13.0

    weekly = await evaluate_metric(
        _FakeDb(_rows()),
        SimpleNamespace(id=7),
        _definition(group_by="week"),
        today=TODAY,
        scope=_scope(),
    )
    assert weekly.value == 3.0
    assert sum(s["value"] for s in weekly.series) == 3.0


def test_verifier_anchored_cte_is_untouched_by_the_snapshot():
    """Migawka dokleja SELECT do CTE, nie zmienia jego treści (płaci nagrody)."""
    import inspect

    from app.services.custom_metrics import engine

    source = inspect.getsource(engine._credited_snapshot)
    assert "VERIFIER_ANCHORED_CTE\n            + f" in source


# ── N1-7 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_team_is_zero_with_a_note_not_my_own_numbers():
    from app.services.custom_metrics.engine import evaluate_metric

    await _clear_snapshot()
    result = await evaluate_metric(
        _FakeDb(_rows()),
        SimpleNamespace(id=7),
        _definition(filters={"author": "team"}),
        today=TODAY,
        scope=_scope("delivery_clients", operators=frozenset()),
    )
    assert result.value == 0.0
    assert result.scope_applied == "team"
    assert any("Nie masz jeszcze zespołu" in n for n in result.notes)


# ── N1-3 / N1-9 ──────────────────────────────────────────────────────────────


def _jobs_sql(author: str, measure: str = "open_now"):
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from app.services.custom_metrics.definition import MetricDefinition
    from app.services.custom_metrics.engine import _jobs_query
    from app.services.custom_metrics.windows import resolve_window

    definition = MetricDefinition.model_validate(
        {"source": "jobs", "measure": measure, "filters": {"author": author}}
    )
    ids = {"me": frozenset({7}), "team": frozenset({7, 9}), "all": None}[author]
    user = SimpleNamespace(id=7, role="sourcer", roles=["sourcer"])
    base, conds, _cols, _ts = _jobs_query(
        definition, resolve_window("last_30_days", TODAY), ids, user
    )
    stmt = select(1).select_from(base).where(*conds)
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_my_jobs_include_collaborators_and_live_assignments(monkeypatch):
    import app.services.workforce_availability as wa

    monkeypatch.setattr(wa, "operational_owner_ids", lambda user: {user.id})
    sql = _jobs_sql("me")
    assert "job_collaborators" in sql
    assert "job_work_assignments" in sql
    assert "delivery_lead_id" in sql and "tac_id" in sql


def test_team_jobs_include_collaborators_and_live_assignments():
    sql = _jobs_sql("team")
    assert "job_collaborators" in sql
    assert "job_work_assignments" in sql


def test_open_now_matches_the_register_open_pill():
    sql = _jobs_sql("all")
    assert "jobs.status != " in sql, sql
    assert "clients.hidden" in sql and "clients.deleted_at IS NULL" in sql
    assert "jobs.status = " not in sql


def test_opened_and_closed_skip_hidden_and_deleted_clients():
    for measure in ("opened", "closed"):
        sql = _jobs_sql("all", measure)
        assert "clients.deleted_at IS NULL" in sql, measure


# ── N1-5 / N1-6 ──────────────────────────────────────────────────────────────


def _tile(**over) -> dict:
    tile = {
        "id": str(uuid.uuid4()),
        "type": "my_tasks",
        "x": 0,
        "y": 0,
        "w": 6,
        "h": 3,
        "config": {"title": "Moje zadania"},
    }
    tile.update(over)
    return tile


def test_dashboard_update_rejects_41_tiles_and_duplicate_ids_in_the_model():
    from app.api.user_dashboard import UserDashboardUpdate

    with pytest.raises(ValidationError):
        UserDashboardUpdate.model_validate(
            {"tiles": [_tile(y=i) for i in range(41)], "expected_version": 0}
        )
    same = _tile()
    with pytest.raises(ValidationError):
        UserDashboardUpdate.model_validate(
            {"tiles": [same, dict(same, y=5)], "expected_version": 0}
        )
    ok = UserDashboardUpdate.model_validate(
        {"tiles": [_tile(y=i) for i in range(40)], "expected_version": 0}
    )
    assert len(ok.tiles) == 40


@pytest.mark.parametrize("key", ["client_ids", "job_ids", "competence_category_ids"])
def test_filter_ids_outside_int4_are_rejected(key):
    with pytest.raises(ValidationError):
        _definition(filters={"author": "me", key: [3_000_000_000]})
    with pytest.raises(ValidationError):
        _definition(filters={"author": "me", key: [0]})
    assert _definition(filters={"author": "me", key: [2**31 - 1]})


async def _login(role: str):
    import app.models  # noqa: F401
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"metric-r10-{marker}@example.com",
            name=f"Metryka r10 {marker}",
            role=UserRole(role),
            roles=[role],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    return {"Authorization": f"Bearer {create_access_token(uid, role)}"}, uid


@needs_db
@pytest.mark.asyncio
async def test_put_dashboard_with_41_tiles_or_duplicate_ids_is_422(app_client):
    headers, _ = await _login("recruiter")
    many = await app_client.put(
        "/api/users/me/dashboard",
        headers=headers,
        json={"tiles": [_tile(y=i) for i in range(41)], "expected_version": 0},
    )
    assert many.status_code == 422, many.text
    same = _tile()
    dup = await app_client.put(
        "/api/users/me/dashboard",
        headers=headers,
        json={"tiles": [same, dict(same, y=5)], "expected_version": 0},
    )
    assert dup.status_code == 422, dup.text


@needs_db
@pytest.mark.asyncio
async def test_evaluate_with_id_outside_int4_is_422(app_client):
    headers, _ = await _login("admin")
    resp = await app_client.post(
        "/api/dashboard-metrics/evaluate",
        headers=headers,
        json={
            "source": "contracts",
            "measure": "started",
            "filters": {"author": "all", "client_ids": [3_000_000_000]},
        },
    )
    assert resp.status_code == 422, resp.text


@needs_db
@pytest.mark.asyncio
async def test_sourcer_counts_a_job_where_they_are_a_collaborator(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.job_collaborator import JobCollaborator

    headers, uid = await _login("sourcer")
    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"metric-r10-{marker}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Metryka r10 {marker}",
            client_id=client.id,
            status=JobStatus.published,
        )
        db.add(job)
        await db.flush()
        db.add(JobCollaborator(job_id=job.id, user_id=uid))
        await db.commit()
        client_id = client.id

    resp = await app_client.post(
        "/api/dashboard-metrics/evaluate",
        headers=headers,
        json={
            "source": "jobs",
            "measure": "open_now",
            "filters": {"author": "me", "client_ids": [client_id]},
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["value"] == 1.0


@needs_db
@pytest.mark.asyncio
async def test_open_jobs_of_a_deleted_client_are_not_counted(app_client):
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    headers, _ = await _login("admin")
    marker = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        gone = Client(name=f"metric-r10-gone-{marker}")
        live = Client(name=f"metric-r10-live-{marker}")
        db.add_all([gone, live])
        await db.flush()
        gone.deleted_at = datetime.now(timezone.utc)
        db.add_all(
            [
                Job(
                    title=f"R10 a {marker}",
                    client_id=gone.id,
                    status=JobStatus.published,
                ),
                Job(title=f"R10 b {marker}", client_id=live.id, status=JobStatus.draft),
                Job(
                    title=f"R10 c {marker}", client_id=live.id, status=JobStatus.closed
                ),
            ]
        )
        await db.commit()
        ids = [gone.id, live.id]

    resp = await app_client.post(
        "/api/dashboard-metrics/evaluate",
        headers=headers,
        json={
            "source": "jobs",
            "measure": "open_now",
            "filters": {"author": "all", "client_ids": ids},
        },
    )
    assert resp.status_code == 200, resp.text
    # Tylko szkic u żywego klienta: zamknięta odpada, usunięty klient też.
    assert resp.json()["value"] == 1.0
