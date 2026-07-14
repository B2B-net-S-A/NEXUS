from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app import background_worker
from app.background_worker import (
    ALL_LOOP_NAMES,
    LeadershipFenced,
    LoopSpec,
    WorkerHealth,
    active_loop_specs,
    all_loop_specs,
    classify_worker_heartbeat,
)
from app.core.config import settings
from app.main import app, lifespan


FULL_SHA = "a" * 40


def _row(**overrides):
    names = sorted(ALL_LOOP_NAMES)
    row = {
        "status": "healthy",
        "heartbeat_at": datetime.now(timezone.utc),
        "expected_tasks": len(names),
        "running_tasks": len(names),
        "task_names": names,
        "fencing_token": 4,
        "version": FULL_SHA,
    }
    row.update(overrides)
    return row


def _classify(row, **kwargs):
    return classify_worker_heartbeat(
        row,
        expected_task_names=ALL_LOOP_NAMES,
        expected_version=FULL_SHA,
        **kwargs,
    )


def test_worker_registry_contains_every_web_era_loop_exactly_once():
    specs = all_loop_specs()
    assert len(specs) == 23
    assert {spec.name for spec in specs} == ALL_LOOP_NAMES
    assert len({spec.name for spec in specs}) == len(specs)
    assert all(callable(spec.factory) and callable(spec.enabled) for spec in specs)


def test_worker_health_serializes_only_operational_metadata():
    health = WorkerHealth(
        "healthy",
        "ok",
        heartbeat_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        expected_tasks=2,
        running_tasks=2,
        task_names=("one", "two"),
        fencing_token=8,
        version=FULL_SHA,
    )
    assert health.as_dict() == {
        "status": "healthy",
        "reason": "ok",
        "heartbeat_at": "2026-07-14T00:00:00+00:00",
        "expected_tasks": 2,
        "running_tasks": 2,
        "task_names": ["one", "two"],
        "fencing_token": 8,
        "version": FULL_SHA,
    }


def test_active_registry_applies_feature_gates_and_rejects_drift(monkeypatch):
    async def _loop():
        return None

    specs = tuple(
        LoopSpec(name, _loop, lambda name=name: name != "signing_sweeper")
        for name in sorted(ALL_LOOP_NAMES)
    )
    monkeypatch.setattr(background_worker, "all_loop_specs", lambda: specs)
    assert "signing_sweeper" not in {spec.name for spec in active_loop_specs()}

    monkeypatch.setattr(background_worker, "all_loop_specs", lambda: specs[:-1])
    with pytest.raises(RuntimeError, match="registry"):
        active_loop_specs()


def test_web_lifespan_contains_no_periodic_task_creation():
    source = inspect.getsource(lifespan)
    assert "calendar_reminder_loop" not in source
    assert "match_history_ttl_loop" not in source
    assert "asyncio.create_task" not in source
    assert "app.state.background_tasks = {}" in source


def test_standalone_worker_configures_all_orm_mappers():
    all_loop_specs()
    from sqlalchemy.orm import configure_mappers

    configure_mappers()


@pytest.mark.parametrize(
    ("row", "reason"),
    [
        (None, "missing"),
        (_row(status="starting"), "worker_reported_unhealthy"),
        (_row(expected_tasks=23, running_tasks=22), "task_count_mismatch"),
        (_row(fencing_token=0), "invalid_fencing_token"),
        (_row(heartbeat_at=None), "invalid_heartbeat"),
        (_row(task_names=[]), "task_registry_mismatch"),
        (_row(version="b" * 40), "version_mismatch"),
    ],
)
def test_worker_heartbeat_rejects_false_green_states(row, reason):
    health = _classify(row)
    assert health.status == "unhealthy"
    assert health.reason == reason


def test_worker_heartbeat_rejects_stale_row():
    now = datetime.now(timezone.utc)
    health = _classify(
        _row(heartbeat_at=now - timedelta(seconds=61)),
        now=now,
        stale_after_seconds=60,
    )
    assert health.status == "unhealthy"
    assert health.reason == "stale"


def test_worker_heartbeat_accepts_fresh_fenced_complete_registry():
    health = _classify(_row())
    assert health.status == "healthy"
    assert health.reason == "ok"
    assert health.fencing_token == 4
    assert set(health.task_names) == ALL_LOOP_NAMES


def test_worker_heartbeat_normalizes_naive_timestamp():
    naive = datetime.now().replace(microsecond=0)
    health = _classify(_row(heartbeat_at=naive), now=naive.replace(tzinfo=timezone.utc))
    assert health.status == "healthy"
    assert health.heartbeat_at is not None
    assert health.heartbeat_at.tzinfo is timezone.utc


@pytest.mark.asyncio
async def test_worker_health_disabled_is_visible_safe_rollout_state(monkeypatch):
    monkeypatch.setattr(settings, "BACKGROUND_WORKER_ENABLED", False)
    health = await background_worker.get_background_worker_health()
    assert health.status == "disabled"
    assert health.reason == "rollout_kill_switch"


class _AsyncContext:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.mark.asyncio
async def test_enabled_worker_health_reads_and_validates_heartbeat(monkeypatch):
    names = frozenset({"calendar_reminder"})
    row = _row(
        expected_tasks=1,
        running_tasks=1,
        task_names=sorted(names),
    )
    result = SimpleNamespace(mappings=lambda: SimpleNamespace(one_or_none=lambda: row))
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    monkeypatch.setattr(settings, "BACKGROUND_WORKER_ENABLED", True)
    monkeypatch.setattr(
        background_worker,
        "active_loop_specs",
        lambda: (LoopSpec("calendar_reminder", AsyncMock()),),
    )
    monkeypatch.setattr(
        background_worker, "AsyncSessionLocal", lambda: _AsyncContext(session)
    )
    monkeypatch.setenv("GIT_SHA", FULL_SHA)

    health = await background_worker.get_background_worker_health()

    assert health.status == "healthy"
    assert health.task_names == ("calendar_reminder",)
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_enabled_worker_health_fails_closed_on_query_error(monkeypatch):
    session = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("secret")))
    monkeypatch.setattr(settings, "BACKGROUND_WORKER_ENABLED", True)
    monkeypatch.setattr(background_worker, "active_loop_specs", lambda: ())
    monkeypatch.setattr(
        background_worker, "AsyncSessionLocal", lambda: _AsyncContext(session)
    )

    health = await background_worker.get_background_worker_health()

    assert health.status == "unhealthy"
    assert health.reason == "query_failed"


@pytest.mark.asyncio
async def test_disabled_worker_is_required_readiness_failure(monkeypatch):
    import app.main as main_module

    async def _healthy() -> None:
        return None

    monkeypatch.setenv("GIT_SHA", FULL_SHA)
    monkeypatch.setattr(main_module, "_probe_database", _healthy)
    monkeypatch.setattr(main_module, "_probe_required_schema", _healthy)
    monkeypatch.setattr(main_module, "_probe_qdrant", _healthy)
    monkeypatch.setattr(settings, "BACKGROUND_WORKER_ENABLED", False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["checks"]["background_worker"] == {
        "status": "unhealthy",
        "critical": True,
        "state": "disabled",
    }


@pytest.mark.asyncio
async def test_stale_instance_cannot_write_heartbeat():
    connection = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=0)),
        commit=AsyncMock(),
    )
    with pytest.raises(LeadershipFenced):
        await background_worker._write_heartbeat(
            connection,
            instance_id="old-instance",
            fencing_token=3,
            tasks={},
            status="unhealthy",
        )

    sql = str(connection.execute.await_args.args[0])
    assert "instance_id = :instance_id" in sql
    assert "fencing_token = :fencing_token" in sql


@pytest.mark.asyncio
async def test_lock_schema_fencing_and_heartbeat_db_primitives(monkeypatch):
    connection = SimpleNamespace(
        scalar=AsyncMock(side_effect=[True, True, 7]),
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)),
        commit=AsyncMock(),
    )
    assert await background_worker._schema_ready(connection) is True
    assert await background_worker._try_advisory_lock(connection) is True
    token = await background_worker._claim_fencing_token(
        connection,
        instance_id="leader",
        started_at=datetime.now(timezone.utc),
        task_names=("one",),
    )
    assert token == 7

    running = asyncio.create_task(asyncio.sleep(60))
    try:
        await background_worker._write_heartbeat(
            connection,
            instance_id="leader",
            fencing_token=token,
            tasks={"one": running},
            status="healthy",
        )
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
    await background_worker._release_advisory_lock(connection)
    assert connection.commit.await_count == 5


@pytest.mark.asyncio
async def test_claim_rejects_missing_fencing_token():
    connection = SimpleNamespace(
        scalar=AsyncMock(return_value=None), commit=AsyncMock()
    )
    with pytest.raises(RuntimeError, match="fencing token"):
        await background_worker._claim_fencing_token(
            connection,
            instance_id="leader",
            started_at=datetime.now(timezone.utc),
            task_names=(),
        )


@pytest.mark.asyncio
async def test_unlock_failure_is_contained():
    connection = SimpleNamespace(
        execute=AsyncMock(side_effect=RuntimeError("connection closed")),
        commit=AsyncMock(),
    )
    await background_worker._release_advisory_lock(connection)


@pytest.mark.asyncio
async def test_heartbeat_supervisor_fails_when_any_loop_exits(monkeypatch):
    completed = asyncio.create_task(asyncio.sleep(0))
    await completed
    write = AsyncMock()
    monkeypatch.setattr(background_worker, "_write_heartbeat", write)

    with pytest.raises(RuntimeError, match="loop"):
        await background_worker._heartbeat_loop(
            SimpleNamespace(),
            instance_id="leader",
            fencing_token=9,
            tasks={"finished": completed},
        )
    assert write.await_args.kwargs["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_healthy_heartbeat_wait_is_cancellation_aware(monkeypatch):
    running = asyncio.create_task(asyncio.Event().wait())
    monkeypatch.setattr(background_worker, "_write_heartbeat", AsyncMock())
    monkeypatch.setattr(
        background_worker.asyncio,
        "sleep",
        AsyncMock(side_effect=asyncio.CancelledError),
    )
    try:
        with pytest.raises(asyncio.CancelledError):
            await background_worker._heartbeat_loop(
                SimpleNamespace(),
                instance_id="leader",
                fencing_token=9,
                tasks={"running": running},
            )
    finally:
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)


@pytest.mark.asyncio
async def test_nonleader_and_missing_schema_start_no_tasks(monkeypatch):
    connection = SimpleNamespace()
    monkeypatch.setattr(
        background_worker,
        "engine",
        SimpleNamespace(connect=lambda: _AsyncContext(connection)),
    )
    monkeypatch.setattr(
        background_worker, "_schema_ready", AsyncMock(return_value=False)
    )
    assert await background_worker._run_leader_once() is False

    monkeypatch.setattr(
        background_worker, "_schema_ready", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        background_worker, "_try_advisory_lock", AsyncMock(return_value=False)
    )
    assert await background_worker._run_leader_once() is False


@pytest.mark.asyncio
async def test_worker_retry_loop_is_cancellation_aware(monkeypatch):
    monkeypatch.setattr(settings, "BACKGROUND_WORKER_ENABLED", True)
    monkeypatch.setattr(
        background_worker,
        "_run_leader_once",
        AsyncMock(side_effect=[RuntimeError("boom"), asyncio.CancelledError]),
    )
    monkeypatch.setattr(background_worker.asyncio, "sleep", AsyncMock())

    with pytest.raises(asyncio.CancelledError):
        await background_worker.run_worker_forever()


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "exit_code"), [("healthy", 0), ("unhealthy", 1)])
async def test_worker_health_cli_exit_code(monkeypatch, capsys, status, exit_code):
    monkeypatch.setattr(
        background_worker,
        "get_background_worker_health",
        AsyncMock(return_value=WorkerHealth(status, "test")),
    )
    assert await background_worker._health_exit_code() == exit_code
    assert f'"status": "{status}"' in capsys.readouterr().out


@pytest.mark.asyncio
async def test_enabled_worker_failure_makes_readiness_503(monkeypatch):
    import app.main as main_module

    async def _healthy() -> None:
        return None

    monkeypatch.setenv("GIT_SHA", FULL_SHA)
    monkeypatch.setattr(main_module, "_probe_database", _healthy)
    monkeypatch.setattr(main_module, "_probe_required_schema", _healthy)
    monkeypatch.setattr(main_module, "_probe_qdrant", _healthy)
    monkeypatch.setattr(settings, "BACKGROUND_WORKER_ENABLED", True)
    monkeypatch.setattr(
        background_worker,
        "get_background_worker_health",
        AsyncMock(return_value=WorkerHealth("unhealthy", "stale")),
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/health")

    assert response.status_code == 503
    assert response.json()["checks"]["background_worker"] == {
        "status": "unhealthy",
        "critical": True,
    }
