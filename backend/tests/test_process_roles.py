"""Web i worker osobno: co musi biec w którym procesie i co widzi `/api/health`."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.core.process_role import (
    EVERY_PROCESS_TASKS,
    WEB_ONLY_TASKS,
    keep_tasks_for_role,
    task_runs_in_role,
)
from app.services import background_task_health as health
from app.services import worker_health

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent


def _compose(name: str) -> dict:
    return yaml.safe_load((REPO / name).read_text())


def _registry_names() -> set[str]:
    """Nazwy z rejestru `lifespan` bez importu aplikacji."""
    source = (BACKEND / "app/main.py").read_text()
    return set(re.findall(r'^ +"([a-z0-9_]+)": asyncio\.create_task', source, re.M))


def test_role_lists_name_real_tasks() -> None:
    assert (WEB_ONLY_TASKS | EVERY_PROCESS_TASKS) <= _registry_names()


def test_web_keeps_only_process_memory_tasks() -> None:
    kept = {n for n in _registry_names() if task_runs_in_role(n, "web")}
    assert kept == WEB_ONLY_TASKS | EVERY_PROCESS_TASKS


def test_worker_leaves_web_memory_tasks() -> None:
    assert not any(task_runs_in_role(n, "worker") for n in WEB_ONLY_TASKS)
    assert task_runs_in_role("auto_full_review", "worker")
    assert task_runs_in_role("runtime_metrics", "worker")


def test_all_keeps_everything() -> None:
    assert all(task_runs_in_role(n, "all") for n in _registry_names())


def test_cancelled_task_runs_no_line() -> None:
    ran: list[str] = []

    async def loop() -> None:
        ran.append("x")

    async def scenario() -> dict:
        tasks = {"auto_full_review": asyncio.create_task(loop())}
        kept = keep_tasks_for_role(tasks, "web")
        await asyncio.gather(*tasks.values(), return_exceptions=True)
        return kept

    assert asyncio.run(scenario()) == {} and ran == []


@pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.staging.yml"])
def test_compose_splits_roles(name: str) -> None:
    services = _compose(name)["services"]
    assert services["backend"]["environment"]["NEXUS_PROCESS_ROLE"].endswith(":-web}")
    worker = services["worker"]
    assert worker["environment"]["NEXUS_PROCESS_ROLE"] == "worker"
    # Dwa procesy w workerze to dwa komplety pętli do blokady lidera.
    assert worker["environment"]["WEB_CONCURRENCY"] == "1"
    assert not worker.get("ports"), "worker nie ma trasy z zewnątrz"


def test_prod_pools_fit_max_connections() -> None:
    services = _compose("docker-compose.yml")["services"]
    limit = next(
        int(arg.split("=")[1])
        for arg in services["postgres"]["command"]
        if str(arg).startswith("max_connections=")
    )
    total = 0
    for name in ("backend", "worker"):
        env = services[name]["environment"]
        total += int(env["DB_POOL_SIZE"]) + int(env["DB_MAX_OVERFLOW"])
    assert total <= limit - 15, "zapas na zrzut bazy i docker exec"


def test_worker_name_stays_outside_backend_prefix() -> None:
    """`scripts/prod_readonly.py` i nocna kopia szukają po `backend-ocgkw`."""
    assert not any(
        s.startswith("backend") and s != "backend"
        for s in _compose("docker-compose.yml")["services"]
    )


def test_entrypoint_worker_skips_migrations() -> None:
    text = (BACKEND / "entrypoint.sh").read_text()
    worker = text.index('"${NEXUS_PROCESS_ROLE:-all}" = "worker"')
    assert worker < text.index("alembic -c alembic/alembic.ini upgrade heads")
    start = (BACKEND / "scripts/worker-start.sh").read_text()
    assert start.index("api/health/live") < start.index("exec uvicorn")
    assert "--workers 1" in start and "DB_STATEMENT_TIMEOUT_MS=120000" in start


def _state(tasks: dict | None, leader=None) -> SimpleNamespace:
    return SimpleNamespace(background_tasks=tasks, background_leader=leader)


def test_local_checks_standby() -> None:
    leader = SimpleNamespace(is_leader=False, standby_seconds=4)
    checks = health.local_background_checks(_state({}, leader))
    assert checks == {"background_tasks": "standby", "ai_features": "standby"}


def test_local_checks_long_standby_alarms() -> None:
    leader = SimpleNamespace(is_leader=False, standby_seconds=301)
    checks = health.local_background_checks(_state({}, leader))
    assert checks["background_tasks"].startswith("unhealthy: standby 301s")


def test_local_checks_crashed_loop_alarms() -> None:
    async def boom() -> None:
        raise RuntimeError("x")

    async def scenario() -> dict[str, str]:
        task = asyncio.create_task(boom())
        await asyncio.gather(task, return_exceptions=True)
        return health.local_background_checks(_state({"petla": task}))

    assert asyncio.run(scenario())["background_tasks"] == "crashed: petla"


def test_local_checks_without_registry() -> None:
    assert health.local_background_checks(_state(None))["background_tasks"] == "unknown"


class _Client:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response, self.error, self.calls = response, error, 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def get(self, _url):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


@pytest.fixture(autouse=True)
def _no_cached_worker_state(monkeypatch):
    monkeypatch.setattr(worker_health, "_cache", None)


def test_unreachable_worker_alarms_uptime_probe(monkeypatch) -> None:
    client = _Client(error=OSError("nope"))
    monkeypatch.setattr(worker_health.httpx, "AsyncClient", lambda **_: client)
    state = asyncio.run(worker_health.fetch_worker_state())
    assert state["checks"]["background_tasks"].startswith("unhealthy: worker")
    assert state["tasks"] is None


def test_worker_state_is_cached(monkeypatch) -> None:
    payload = {"checks": {"background_tasks": "healthy"}, "tasks": {"running": 9}}
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)
    client = _Client(response=response)
    monkeypatch.setattr(worker_health.httpx, "AsyncClient", lambda **_: client)

    async def twice():
        await worker_health.fetch_worker_state()
        return await worker_health.fetch_worker_state()

    assert asyncio.run(twice()) == payload
    assert client.calls == 1


def test_worker_ws_goes_through_bus(monkeypatch) -> None:
    from app.api import ws

    sent: list[tuple[str, dict]] = []

    async def publish(topic: str, data: dict) -> bool:
        sent.append((topic, data))
        return True

    monkeypatch.setattr(ws.settings, "NEXUS_PROCESS_ROLE", "worker")
    monkeypatch.setattr(ws.process_bus, "publish", publish)
    asyncio.run(ws.manager.notify_user(7, {"type": "notification"}))
    assert sent == [("ws_notify", {"user_id": 7, "event": {"type": "notification"}})]


def test_bus_message_does_not_bounce_in_worker(monkeypatch) -> None:
    from app.api import ws

    called: list[int] = []

    async def notify(user_id: int, _event: dict) -> None:
        called.append(user_id)

    monkeypatch.setattr(ws.manager, "notify_user", notify)
    monkeypatch.setattr(ws.settings, "NEXUS_PROCESS_ROLE", "worker")
    asyncio.run(ws._on_ws_notify({"user_id": 7, "event": {}}))
    assert called == []
    monkeypatch.setattr(ws.settings, "NEXUS_PROCESS_ROLE", "web")
    asyncio.run(ws._on_ws_notify({"user_id": 7, "event": {}}))
    assert called == [7]


def test_oversized_bus_payload_is_refused() -> None:
    from app.core import process_bus

    data = {"x": "ą" * process_bus.MAX_PAYLOAD_BYTES}
    assert asyncio.run(process_bus.publish("t", data)) is False


def test_lock_is_noop_in_single_process(monkeypatch) -> None:
    from app.core import process_lock

    async def boom(*_a, **_k):
        raise AssertionError("rola all nie łączy się z bazą")

    monkeypatch.setattr(process_lock.settings, "NEXUS_PROCESS_ROLE", "all")
    monkeypatch.setattr(process_lock.asyncpg, "connect", boom)

    async def scenario() -> bool:
        async with process_lock.cross_process_lock("x") as owned:
            return owned

    assert asyncio.run(scenario()) is True
