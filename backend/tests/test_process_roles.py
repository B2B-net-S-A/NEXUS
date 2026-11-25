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


def test_worker_reads_corpus_readiness_and_web_does_not() -> None:
    assert "keyword_corpus_readiness" in _registry_names()
    assert task_runs_in_role("keyword_corpus_readiness", "worker")
    assert not task_runs_in_role("keyword_corpus_readiness", "web")


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
    pools = {}
    for name in ("backend", "worker"):
        env = services[name]["environment"]
        pools[name] = int(env["DB_POOL_SIZE"]) + int(env["DB_MAX_OVERFLOW"])
    # Pula jest na proces, a backend ma do WEB_PROCESSES_MAX procesów web.
    # Rolling update (etap B2): przez chwilę dwa kontenery tej samej roli naraz.
    web = pools["backend"] * WEB_PROCESSES_MAX
    worker = pools["worker"]
    worst = max(2 * web + worker, web + 2 * worker)
    assert worst <= limit - 15, "zapas na zrzut bazy, blokady i docker exec"


# Ile procesów web obejmują budżety w compose (max_connections, mem_limit).
WEB_PROCESSES_MAX = 2

# Budżet pamięci Postgresa po OOM cgroupa 25.11.2026 o 10:19 (pomiar memory.stat
# tego dnia o 14:01). Trzymane połączenie kosztuje ok. 35 MiB: RssAnon (mediana
# 28 MB) i ok. 7 MB tablic stron, bo shmem jest mapowany stronami 4 kB. Poza
# pulami jest 16 połączeń: trzy małe silniki bez nazwy na proces, bus, lider
# i kopia. Pamięć współdzielona to 8409 MB przy shared_buffers 8 GB.
# → docs/claude/podstawy/pamiec-postgresa.md
MIB = 1024**2
GIB = 1024**3
PG_CONNECTION_MIB = 35
PG_OTHER_CONNECTIONS = 16
PG_SHMEM_PER_BUFFER_BYTE = 8409 / 8192
PG_KERNEL_REST_GIB = 0.1
PG_AUTOVACUUM_WORKERS = 3  # domyślne autovacuum_max_workers
PG_HEADROOM_GIB = 2


def _bytes(size: str) -> int:
    value, unit = re.fullmatch(r"(\d+)([kmg])b?", size.strip().lower()).groups()
    return int(value) * {"k": 1024, "m": MIB, "g": GIB}[unit]


def test_prod_postgres_memory_leaves_headroom() -> None:
    """Bufor, trzymane połączenia i autovacuum muszą zostawić 2 GiB na zapytania.

    Zapas jest na `work_mem` (16 MB na węzeł planu, hash × 2) i pamięć
    współdzieloną zapytań równoległych. Kontener nie ma swapu, a page cache
    w tym samym limicie da się odzyskać, więc go tu nie liczymy.
    """
    services = _compose("docker-compose.yml")["services"]
    postgres = services["postgres"]
    pg = dict(str(arg).split("=", 1) for arg in postgres["command"] if "=" in str(arg))
    # autovacuum_work_mem=-1 (domyślne) znaczy maintenance_work_mem na każdy worker.
    autovacuum = pg.get("autovacuum_work_mem", pg["maintenance_work_mem"])
    held = (
        WEB_PROCESSES_MAX * int(services["backend"]["environment"]["DB_POOL_SIZE"])
        + int(services["worker"]["environment"]["DB_POOL_SIZE"])
        + PG_OTHER_CONNECTIONS
    )
    used = (
        _bytes(pg["shared_buffers"]) * PG_SHMEM_PER_BUFFER_BYTE
        + held * PG_CONNECTION_MIB * MIB
        + PG_AUTOVACUUM_WORKERS * _bytes(autovacuum)
        + PG_KERNEL_REST_GIB * GIB
    )
    headroom = _bytes(postgres["mem_limit"]) - used
    assert headroom >= PG_HEADROOM_GIB * GIB, (
        f"zapas {headroom / GIB:.2f} GiB przy {held} trzymanych połączeniach"
    )


def test_backend_web_concurrency_is_a_switch_defaulting_to_one() -> None:
    """Drugi proces web włącza się zmienną w Coolify, nie zmianą compose.

    Decyzja Artura 24.11.2026: PR wnosi poprawki stanu, a drugi proces startuje
    dopiero po „Coolify set env” NEXUS_WEB_CONCURRENCY=2.
    """
    backend = _compose("docker-compose.yml")["services"]["backend"]
    assert backend["environment"]["WEB_CONCURRENCY"] == "${NEXUS_WEB_CONCURRENCY:-1}"
    # Dwa procesy po ok. 1,9 GB RSS (pomiar 24.11.2026) nie mieszczą się w 4g.
    assert backend["mem_limit"] == "6g"


def test_worker_name_stays_outside_backend_prefix() -> None:
    """`scripts/prod_readonly.py` i nocna kopia szukają po `backend-ocgkw`."""
    assert not any(
        s.startswith("backend") and s != "backend"
        for s in _compose("docker-compose.yml")["services"]
    )


def test_entrypoint_runs_several_processes_only_in_web_role() -> None:
    """Rola `all` (wycofanie) z NEXUS_WEB_CONCURRENCY=2 dałaby dwa procesy `all`.

    W `all` blokady doradcze i bus są wyłączone, a pętle ma tylko lider, więc
    entrypoint wraca wtedy do jednego procesu.
    """
    text = (BACKEND / "entrypoint.sh").read_text()
    guard = text.index(
        'if [ "${NEXUS_PROCESS_ROLE:-all}" != "web" ] && [ "${WEB_CONCURRENCY:-1}" != "1" ]; then'
    )
    assert "export WEB_CONCURRENCY=1" in text[guard : guard + 300]
    assert guard < text.index("exec uvicorn app.main:app")


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

    monkeypatch.setattr(ws.manager, "deliver_local", notify)
    monkeypatch.setattr(ws.settings, "NEXUS_PROCESS_ROLE", "worker")
    asyncio.run(ws._on_ws_notify({"user_id": 7, "event": {}}))
    assert called == []
    monkeypatch.setattr(ws.settings, "NEXUS_PROCESS_ROLE", "web")
    asyncio.run(ws._on_ws_notify({"user_id": 7, "event": {}}))
    assert called == [7]


def test_oversized_bus_payload_is_refused() -> None:
    from app.core import process_bus

    # Powyżej limitu NOTIFY wiadomość idzie w kawałkach; odmowa dopiero ponad MAX_MESSAGE_BYTES.
    data = {"x": "ą" * process_bus.MAX_MESSAGE_BYTES}
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
