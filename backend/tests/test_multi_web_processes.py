"""Kilka procesów web (WEB_CONCURRENCY > 1): stan, który musi przejść między nimi.

→ docs/claude/podstawy/kilka-procesow-web.md
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import List

import pytest
from limits import parse_many

from app.core import process_bus
from app.core.process_role import web_process_count


class FakeUser:
    def __init__(self, user_id: int, name: str):
        self.id = user_id
        self.name = name


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: List[dict] = []

    async def accept(self, subprotocol=None) -> None:  # noqa: ARG002
        return None

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, code: int, reason: str) -> None:  # noqa: ARG002
        return None


@pytest.fixture
def two_webs(monkeypatch):
    """Ten proces jest jednym z dwóch procesów web; bus nagrywa zamiast wysyłać."""
    monkeypatch.setattr(process_bus.settings, "NEXUS_PROCESS_ROLE", "web")
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    published: list[tuple[str, dict]] = []

    def publish_soon(topic: str, data: dict) -> None:
        published.append((topic, data))

    async def publish(topic: str, data: dict) -> bool:
        published.append((topic, data))
        return True

    monkeypatch.setattr(process_bus, "publish_soon", publish_soon)
    monkeypatch.setattr(process_bus, "publish", publish)
    return published


# ── liczba procesów ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("role", "env", "expected"),
    [
        ("web", "2", 2),
        ("web", None, 1),
        ("web", "abc", 1),
        ("web", "0", 1),
        ("worker", "2", 1),
        ("all", "2", 1),
    ],
)
def test_web_process_count(monkeypatch, role, env, expected) -> None:
    monkeypatch.setattr(process_bus.settings, "NEXUS_PROCESS_ROLE", role)
    if env is None:
        monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    else:
        monkeypatch.setenv("WEB_CONCURRENCY", env)
    assert web_process_count() == expected


# ── bus: własne wiadomości ─────────────────────────────────────────────────────


def test_others_only_topic_skips_own_notify() -> None:
    got: list[dict] = []

    async def handler(data: dict) -> None:
        got.append(data)

    process_bus.subscribe("t_others", handler, others_only=True)
    own = {"t": "t_others", "d": {"n": 1}, "o": process_bus.PROCESS_TOKEN}
    other = {"t": "t_others", "d": {"n": 2}, "o": "inny-proces"}
    asyncio.run(process_bus.dispatch(json.dumps(own)))
    asyncio.run(process_bus.dispatch(json.dumps(other)))
    assert got == [{"n": 2}]


def test_plain_topic_still_gets_own_notify() -> None:
    got: list[dict] = []

    async def handler(data: dict) -> None:
        got.append(data)

    process_bus.subscribe("t_all", handler)
    own = {"t": "t_all", "d": {"n": 1}, "o": process_bus.PROCESS_TOKEN}
    asyncio.run(process_bus.dispatch(json.dumps(own)))
    assert got == [{"n": 1}]


def test_publish_soon_is_noop_in_single_process(monkeypatch) -> None:
    monkeypatch.setattr(process_bus.settings, "NEXUS_PROCESS_ROLE", "all")

    async def boom(*_a, **_k):
        raise AssertionError("rola all nie wysyła NOTIFY")

    monkeypatch.setattr(process_bus, "publish", boom)

    async def scenario() -> None:
        process_bus.publish_soon("x", {})
        await asyncio.sleep(0)

    asyncio.run(scenario())


def test_large_message_goes_in_chunks_and_is_reassembled() -> None:
    """Ramka czatu z długą wiadomością (do 10 000 znaków) nie mieści się w NOTIFY."""
    import random

    got: list[dict] = []

    async def handler(data: dict) -> None:
        got.append(data)

    process_bus.subscribe("t_big", handler, others_only=True)
    event = {
        "type": "chat:message:new",
        "data": {"message": {"content": "żółć " * 2000}},
    }
    payload = json.dumps(
        {"t": "t_big", "d": event, "o": "inny-proces"}, ensure_ascii=False
    )
    parts = process_bus.notify_payloads(payload)
    assert parts is not None and len(parts) > 1
    assert all(len(p.encode()) <= process_bus.MAX_PAYLOAD_BYTES for p in parts)
    random.Random(7).shuffle(parts)  # kolejność dispatchu nie ma znaczenia

    async def scenario() -> None:
        for part in parts:
            await process_bus.dispatch(part)

    asyncio.run(scenario())
    assert got == [event]
    assert process_bus._partials == {}


def test_own_large_message_is_still_skipped_for_others_only() -> None:
    got: list[dict] = []

    async def handler(data: dict) -> None:
        got.append(data)

    process_bus.subscribe("t_big_own", handler, others_only=True)
    payload = json.dumps(
        {"t": "t_big_own", "d": {"x": "ą" * 9000}, "o": process_bus.PROCESS_TOKEN},
        ensure_ascii=False,
    )
    parts = process_bus.notify_payloads(payload)
    assert parts is not None and len(parts) > 1

    async def scenario() -> None:
        for part in parts:
            await process_bus.dispatch(part)

    asyncio.run(scenario())
    assert got == []


def test_small_message_is_one_notify_and_huge_is_refused() -> None:
    assert process_bus.notify_payloads('{"t": "x"}') == ['{"t": "x"}']
    assert process_bus.notify_payloads("ą" * process_bus.MAX_MESSAGE_BYTES) is None


def test_incomplete_chunks_expire(monkeypatch) -> None:
    payload = json.dumps({"t": "t_lost", "d": {"x": "a" * 20000}, "o": "inny"})
    parts = process_bus.notify_payloads(payload)
    asyncio.run(process_bus.dispatch(parts[0]))
    assert len(process_bus._partials) == 1
    later = time.monotonic() + 61
    monkeypatch.setattr(process_bus.time, "monotonic", lambda: later)
    other = process_bus.notify_payloads(
        json.dumps({"t": "t_lost", "d": {"x": "b" * 20000}, "o": "inny"})
    )
    asyncio.run(process_bus.dispatch(other[0]))
    assert list(process_bus._partials) == [json.loads(other[0])["c"]]
    process_bus._partials.clear()


# ── powiadomienia na żywo ──────────────────────────────────────────────────────


def test_web_notify_delivers_locally_and_tells_other_webs(two_webs) -> None:
    from app.api.ws import ConnectionManager

    manager = ConnectionManager()
    socket = FakeWebSocket()
    manager._connections[5] = [socket]
    event = {"type": "pipeline_changed", "job_id": 1}
    asyncio.run(manager.notify_user(5, event))
    assert socket.sent and socket.sent[-1]["type"] == "pipeline_changed"
    assert two_webs == [("ws_notify", {"user_id": 5, "event": event})]


def test_single_web_notify_does_not_touch_the_bus(monkeypatch) -> None:
    from app.api.ws import ConnectionManager

    monkeypatch.setattr(process_bus.settings, "NEXUS_PROCESS_ROLE", "web")
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)

    def boom(*_a, **_k):
        raise AssertionError("jeden proces web nie potrzebuje busa")

    monkeypatch.setattr(process_bus, "publish_soon", boom)
    manager = ConnectionManager()
    asyncio.run(manager.notify_user(5, {"type": "x"}))


def test_frame_from_other_web_is_delivered_without_republishing(two_webs) -> None:
    from app.api import ws

    socket = FakeWebSocket()
    ws.manager._connections[777001] = [socket]
    try:
        asyncio.run(
            ws._on_ws_notify({"user_id": 777001, "event": {"type": "pipeline_changed"}})
        )
    finally:
        ws.manager._connections.pop(777001, None)
    assert socket.sent and socket.sent[-1]["type"] == "pipeline_changed"
    assert two_webs == [], "ramka z innego procesu nie wraca na bus"


# ── obecność („kto ogląda”) ────────────────────────────────────────────────────


def test_presence_is_shared_between_web_processes(two_webs) -> None:
    from app.api.ws import ConnectionManager

    process_a, process_b = ConnectionManager(), ConnectionManager()
    ws_a, ws_b = FakeWebSocket(), FakeWebSocket()

    async def scenario() -> None:
        await process_a.subscribe(FakeUser(1, "Anna"), ws_a, "candidate", 42)
        # Proces A ogłasza swoich widzów; B dostaje to przez bus.
        topic, data = two_webs[-1]
        assert topic == "ws_presence"
        await process_b.apply_remote_presence("A", data["keys"])
        await process_b.subscribe(FakeUser(2, "Bartek"), ws_b, "candidate", 42)
        topic, data = two_webs[-1]
        await process_a.apply_remote_presence("B", data["keys"])

    asyncio.run(scenario())
    for manager, ws in ((process_a, ws_a), (process_b, ws_b)):
        assert {v["user_id"] for v in manager.get_viewers("candidate", 42)} == {1, 2}
        assert manager.viewer_ids("candidate", 42) == {1, 2}
        assert {v["user_id"] for v in ws.sent[-1]["viewers"]} == {1, 2}


def test_presence_leave_in_other_process_is_seen(two_webs) -> None:
    from app.api.ws import ConnectionManager

    local, remote = ConnectionManager(), ConnectionManager()
    ws_local, ws_remote = FakeWebSocket(), FakeWebSocket()

    async def scenario() -> None:
        await local.subscribe(FakeUser(1, "Anna"), ws_local, "job", 7)
        await remote.subscribe(FakeUser(2, "Bartek"), ws_remote, "job", 7)
        await local.apply_remote_presence("B", two_webs[-1][1]["keys"])
        await remote.unsubscribe(2, ws_remote, "job", 7)
        assert two_webs[-1][1]["keys"] == {"job:7": []}
        await local.apply_remote_presence("B", two_webs[-1][1]["keys"])

    asyncio.run(scenario())
    assert local.viewer_ids("job", 7) == {1}
    assert [v["user_id"] for v in ws_local.sent[-1]["viewers"]] == [1]


def test_same_person_in_two_processes_is_one_viewer(two_webs) -> None:
    from app.api.ws import ConnectionManager

    local = ConnectionManager()

    async def scenario() -> None:
        await local.subscribe(FakeUser(1, "Anna"), FakeWebSocket(), "job", 7)
        await local.apply_remote_presence(
            "B",
            {
                "job:7": [
                    {
                        "user_id": 1,
                        "name": "Anna",
                        "editing": ["notes"],
                        "since": "2000-01-01T00:00:00+00:00",
                    }
                ]
            },
        )

    asyncio.run(scenario())
    viewers = local.get_viewers("job", 7)
    assert len(viewers) == 1
    assert viewers[0]["editing"] == ["notes"]
    assert viewers[0]["since"] == "2000-01-01T00:00:00+00:00"


def test_remote_presence_expires_without_heartbeat(two_webs, monkeypatch) -> None:
    from app.api import ws

    manager = ws.ConnectionManager()
    socket = FakeWebSocket()

    async def scenario() -> None:
        await manager.subscribe(FakeUser(1, "Anna"), socket, "job", 7)
        await manager.apply_remote_presence(
            "B", {"job:7": [{"user_id": 2, "name": "Bartek", "editing": []}]}
        )
        assert manager.viewer_ids("job", 7) == {1, 2}
        later = time.monotonic() + ws.PRESENCE_REMOTE_TTL_SECONDS + 1
        monkeypatch.setattr(ws.time, "monotonic", lambda: later)
        assert manager.viewer_ids("job", 7) == {1}
        await manager.prune_remote_presence()

    asyncio.run(scenario())
    assert manager._remote == {}
    assert [v["user_id"] for v in socket.sent[-1]["viewers"]] == [1]


def test_older_presence_message_after_newer_leaves_no_ghost(two_webs) -> None:
    """Wejście i wyjście tuż po sobie: NOTIFY z dwóch transakcji bywa odwrócone."""
    from app.api.ws import ConnectionManager

    local, remote = ConnectionManager(), ConnectionManager()
    ws_remote = FakeWebSocket()

    async def scenario() -> None:
        await remote.subscribe(FakeUser(2, "Bartek"), ws_remote, "job", 7)
        entered = two_webs[-1][1]
        await remote.unsubscribe(2, ws_remote, "job", 7)
        left = two_webs[-1][1]
        assert entered["seq"] < left["seq"]
        await local.apply_remote_presence("B", left["keys"], left["seq"])
        await local.apply_remote_presence("B", entered["keys"], entered["seq"])

    asyncio.run(scenario())
    assert local.viewer_ids("job", 7) == set()


def test_cache_evict_local_does_not_tell_other_processes(two_webs) -> None:
    from app.core import cache

    async def scenario() -> None:
        await cache.cache_set("kpi:milestones:v2:old", {"x": 1}, ttl_seconds=60)
        await cache.cache_evict_local("kpi:milestones:v2:")
        assert await cache.cache_get("kpi:milestones:v2:old") is None

    asyncio.run(scenario())
    assert two_webs == []


@pytest.mark.parametrize(
    "path", ["app/services/kpi_engine.py", "app/services/custom_metrics/engine.py"]
)
def test_snapshot_housekeeping_stays_local(path) -> None:
    """Sprzątanie starszych migawek przed zapisem nowej nie może iść przez bus.

    Rozgłoszone kasowałoby drugiemu procesowi jego świeżą migawkę i oba liczyły
    ciężkie CTE na zmianę (przegląd PR-a 24.11.2026).
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / path).read_text()
    assert "cache_invalidate(" not in source
    assert "cache_evict_local(" in source


def test_presence_snapshot_fits_notify(two_webs) -> None:
    from app.api.ws import ConnectionManager

    manager = ConnectionManager()

    async def scenario() -> None:
        for job_id in range(400):
            await manager.subscribe(
                FakeUser(job_id, f"Osoba {job_id}"), FakeWebSocket(), "job", job_id
            )

    asyncio.run(scenario())
    chunks = manager.presence_snapshot_messages()
    assert len(chunks) > 1
    assert sum(len(c) for c in chunks) == 400
    for keys in chunks:
        payload = json.dumps(
            {
                "t": "ws_presence",
                "d": {"origin": process_bus.PROCESS_TOKEN, "keys": keys, "seq": 10**9},
                "o": process_bus.PROCESS_TOKEN,
            },
            ensure_ascii=False,
        )
        assert len(payload.encode()) <= process_bus.MAX_PAYLOAD_BYTES


# ── limity slowapi ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "processes", "expected"),
    [
        ("30/minute", 1, "30/minute"),
        ("30/minute", 2, "15/1 minute"),
        ("5/minute; 30/hour", 2, "3/1 minute; 15/1 hour"),
        ("3/minute", 2, "2/1 minute"),
        ("1/minute", 2, "1/1 minute"),
    ],
)
def test_limit_is_shared_between_processes(value, processes, expected) -> None:
    from app.core.rate_limit import share_per_process

    shared = share_per_process(value, processes)
    assert shared == expected
    parse_many(shared)  # slowapi musi to umieć przeczytać


def test_limiter_divides_limits_when_two_webs(two_webs) -> None:
    from app.core.rate_limit import ProcessShareLimiter, client_ip_key

    limiter = ProcessShareLimiter(
        key_func=client_ip_key, default_limits=[], key_style="endpoint"
    )

    @limiter.limit("10/minute")
    async def static_route(request):  # noqa: ARG001
        return None

    def per_key(key: str) -> str:
        return "8/minute" if key else "4/minute"

    @limiter.limit(per_key)
    async def dynamic_route(request):  # noqa: ARG001
        return None

    static = limiter._route_limits[f"{__name__}.static_route"]
    assert [lim.limit.amount for lim in static] == [5]
    dynamic = limiter._dynamic_route_limits[f"{__name__}.dynamic_route"]
    provider = dynamic[0]._LimitGroup__limit_provider
    assert provider("x") == "4/1 minute"


def test_app_limiter_shares_limits() -> None:
    from app.core.rate_limit import ProcessShareLimiter, limiter

    assert isinstance(limiter, ProcessShareLimiter)


# ── unieważnienia i „Zatrzymaj” ────────────────────────────────────────────────


def test_policy_invalidation_reaches_other_processes(two_webs) -> None:
    from app.services import policy_cache

    policy_cache._snapshot = object()  # type: ignore[assignment]
    policy_cache.invalidate_policy_cache()
    assert policy_cache._snapshot is None
    assert two_webs == [("policy_cache_invalidate", {})]

    policy_cache._snapshot = object()  # type: ignore[assignment]
    asyncio.run(policy_cache._on_remote_invalidate({}))
    assert policy_cache._snapshot is None


def test_cache_invalidation_reaches_other_processes(two_webs) -> None:
    from app.core import cache

    async def scenario() -> None:
        await cache.cache_set("kpis:team:1", {"x": 1}, ttl_seconds=60)
        await cache.cache_invalidate("kpis:")
        assert await cache.cache_get("kpis:team:1") is None
        await cache.cache_set("kpis:team:1", {"x": 1}, ttl_seconds=60)
        await cache._on_remote_invalidate({"prefix": "kpis:"})
        assert await cache.cache_get("kpis:team:1") is None

    asyncio.run(scenario())
    assert two_webs == [("cache_invalidate", {"prefix": "kpis:"})]


def test_jarvis_stop_reaches_the_process_running_the_turn(two_webs) -> None:
    from app.services.jarvis import agent

    conversation_id = uuid.uuid4()
    agent.request_cancel(conversation_id)
    assert two_webs == [("jarvis_cancel", {"conversation_id": str(conversation_id)})]
    agent._CANCEL_REQUESTS.discard(conversation_id)

    asyncio.run(agent._on_remote_cancel({"conversation_id": str(conversation_id)}))
    assert conversation_id in agent._CANCEL_REQUESTS
    agent._CANCEL_REQUESTS.discard(conversation_id)


def test_job_twin_reset_reaches_other_processes(two_webs) -> None:
    from app.services import job_twins

    job_twins._suggestion_cache["items"] = ["x"]
    asyncio.run(job_twins._on_remote_reset({}))
    assert job_twins._suggestion_cache["items"] is None
    job_twins.reset_suggestion_cache()
    assert two_webs == [("job_twins_reset", {})]


# ── limity zewnętrznych API w pamięci procesu ─────────────────────────────────


def test_white_list_daily_quota_is_shared(two_webs) -> None:
    from app.services.hr import white_list

    white_list.reset_memory()
    try:
        assert white_list.usage()["limits"] == {"search": 50, "check": 50}
        memory = white_list._today_memory()
        for _ in range(50):
            white_list._consume(memory, "check")
        with pytest.raises(white_list.WhiteListError):
            white_list._consume(memory, "check")
    finally:
        white_list.reset_memory()


def test_ksef_preview_hourly_budget_is_shared(two_webs) -> None:
    from app.services.finance_ledger import invoice_preview

    invoice_preview._downloads.clear()
    try:
        taken = 0
        while invoice_preview._take_slot():
            taken += 1
        assert taken == invoice_preview.ON_DEMAND_PER_HOUR // 2
    finally:
        invoice_preview._downloads.clear()


# ── pętle web, które przy dwóch procesach pisałyby podwójnie ──────────────────


def test_second_web_follows_corpus_readiness_instead_of_writing(
    two_webs, monkeypatch
) -> None:
    from contextlib import asynccontextmanager

    from app.tasks import keyword_corpus_backfill as kcb

    calls: list[str] = []

    @asynccontextmanager
    async def lock_held_elsewhere(_name: str, item: int = 0):  # noqa: ARG001
        yield False

    async def phases() -> None:
        calls.append("phases")

    async def follow() -> None:
        calls.append("follow")

    monkeypatch.setattr(kcb, "cross_process_lock", lock_held_elsewhere)
    monkeypatch.setattr(kcb, "_backfill_phases", phases)
    monkeypatch.setattr(kcb, "_follow_readiness", follow)
    asyncio.run(kcb.keyword_corpus_backfill_loop())
    assert calls == ["follow"]


def test_startup_wait_lock_is_noop_in_single_process(monkeypatch) -> None:
    from app.core import process_lock

    async def boom(*_a, **_k):
        raise AssertionError("rola all nie łączy się z bazą")

    monkeypatch.setattr(process_lock.settings, "NEXUS_PROCESS_ROLE", "all")
    monkeypatch.setattr(process_lock.asyncpg, "connect", boom)

    async def scenario() -> bool:
        async with process_lock.cross_process_wait_lock(
            "startup_oneoffs", timeout_seconds=1
        ) as got:
            return got

    assert asyncio.run(scenario()) is True


def test_startup_wait_lock_goes_on_without_database(monkeypatch) -> None:
    from app.core import process_lock

    async def refused(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr(process_lock.settings, "NEXUS_PROCESS_ROLE", "web")
    monkeypatch.setattr(process_lock.asyncpg, "connect", refused)

    async def scenario() -> bool:
        async with process_lock.cross_process_wait_lock(
            "startup_oneoffs", timeout_seconds=1
        ) as got:
            return got

    assert asyncio.run(scenario()) is False
