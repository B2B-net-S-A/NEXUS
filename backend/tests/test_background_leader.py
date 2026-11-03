"""Jeden właściciel pętli w tle, gdy przy wdrożeniu żyją dwa kontenery.

Rolling update oznacza kilkanaście sekund z dwoma procesami. Pętle nie mają
własnego wyboru lidera, więc dwa komplety to podwójne maile, alerty i importy.
Plan: `docs/claude/podstawy/przerwa-przy-wdrozeniu.md`, etap 3.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import asyncpg
import pytest

from app.core.background_leader import BackgroundLeader
from app.core.config import settings

_BACKEND = Path(__file__).resolve().parents[1]
_DSN = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")


def _leader(calls: list[str], *, name: str = "a", lock_key: int = 91_000_001) -> BackgroundLeader:
    async def acquired() -> None:
        calls.append(f"{name}:acquired")

    async def lost() -> None:
        calls.append(f"{name}:lost")

    return BackgroundLeader(
        _DSN,
        on_acquired=acquired,
        on_lost=lost,
        lock_key=lock_key,
        retry_seconds=0.05,
        check_seconds=0.05,
    )


async def _until(condition, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "warunek nie spełniony na czas"
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_free_lock_starts_loops_before_startup_finishes() -> None:
    """Zwykły start bez nakładania: pętle ruszają jak dotąd, przed `yield`."""
    calls: list[str] = []
    leader = _leader(calls)
    await leader.start()
    try:
        assert leader.is_leader is True
        assert calls == ["a:acquired"]
    finally:
        await leader.stop_watching()
        await leader.release()


@pytest.mark.asyncio
async def test_second_process_waits_and_takes_over_after_release() -> None:
    calls: list[str] = []
    first = _leader(calls, name="a", lock_key=91_000_002)
    second = _leader(calls, name="b", lock_key=91_000_002)
    await first.start()
    await second.start()
    try:
        await asyncio.sleep(0.2)
        assert second.is_leader is False
        assert calls == ["a:acquired"], "drugi proces nie startuje pętli"

        await first.stop_watching()
        await first.release()
        await _until(lambda: second.is_leader)
        assert calls == ["a:acquired", "b:acquired"]
    finally:
        await second.stop_watching()
        await second.release()


@pytest.mark.asyncio
async def test_killed_process_frees_the_lock_without_release() -> None:
    """SIGKILL starego kontenera: Postgres zwalnia blokadę razem z połączeniem."""
    calls: list[str] = []
    holder = await asyncpg.connect(_DSN)
    assert await holder.fetchval("SELECT pg_try_advisory_lock($1)", 91_000_003)
    waiting = _leader(calls, name="b", lock_key=91_000_003)
    await waiting.start()
    try:
        assert waiting.is_leader is False
        holder.terminate()
        await _until(lambda: waiting.is_leader)
        assert calls == ["b:acquired"]
    finally:
        await waiting.stop_watching()
        await waiting.release()


@pytest.mark.asyncio
async def test_lost_connection_is_reacquired_without_touching_the_loops() -> None:
    """Chwilowe zerwanie połączenia nie może restartować kompletu pętli."""
    calls: list[str] = []
    leader = _leader(calls, lock_key=91_000_004)
    await leader.start()
    try:
        leader._conn.terminate()  # noqa: SLF001
        await asyncio.sleep(0.3)
        assert leader.is_leader is True
        assert leader._conn is not None and not leader._conn.is_closed()  # noqa: SLF001
        assert calls == ["a:acquired"]
    finally:
        await leader.stop_watching()
        await leader.release()


@pytest.mark.asyncio
async def test_lock_taken_by_another_process_stops_the_loops() -> None:
    """Zerwane połączenie, a blokadę ma już ktoś inny: dwa komplety pętli to
    podwójne maile, więc ten proces oddaje pętle."""
    calls: list[str] = []
    leader = _leader(calls, lock_key=91_000_005)
    await leader.start()
    other = await asyncpg.connect(_DSN)
    try:
        await leader._conn.close()  # noqa: SLF001
        assert await other.fetchval("SELECT pg_try_advisory_lock($1)", 91_000_005)
        await _until(lambda: not leader.is_leader)
        assert calls == ["a:acquired", "a:lost"]
    finally:
        await other.close()
        await leader.stop_watching()
        await leader.release()


@pytest.mark.asyncio
async def test_database_down_at_start_stays_standby_and_retries() -> None:
    attempts = {"n": 0}
    calls: list[str] = []

    async def flaky_connect(*_args, **_kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OSError("baza wstaje")
        return await asyncpg.connect(_DSN)

    async def acquired() -> None:
        calls.append("acquired")

    async def lost() -> None:
        calls.append("lost")

    leader = BackgroundLeader(
        _DSN,
        on_acquired=acquired,
        on_lost=lost,
        lock_key=91_000_006,
        retry_seconds=0.02,
        check_seconds=0.02,
        connect=flaky_connect,
    )
    await leader.start()
    try:
        assert leader.is_leader is False
        await _until(lambda: leader.is_leader)
        assert calls == ["acquired"]
    finally:
        await leader.stop_watching()
        await leader.release()


@pytest.mark.asyncio
async def test_database_gone_after_losing_connection_keeps_the_loops() -> None:
    """Brak bazy to nie utrata blokady: nikt inny nie wykona pracy, pętle ponawiają."""
    state = {"down": False}
    calls: list[str] = []

    async def connect(*args, **kwargs):
        if state["down"]:
            raise OSError("baza leży")
        return await asyncpg.connect(*args, **kwargs)

    async def acquired() -> None:
        calls.append("acquired")

    async def lost() -> None:
        calls.append("lost")

    leader = BackgroundLeader(
        _DSN,
        on_acquired=acquired,
        on_lost=lost,
        lock_key=91_000_008,
        retry_seconds=0.02,
        check_seconds=0.02,
        connect=connect,
    )
    await leader.start()
    try:
        state["down"] = True
        leader._conn.terminate()  # noqa: SLF001
        await asyncio.sleep(0.2)
        assert leader.is_leader is True
        assert leader._watcher is not None and not leader._watcher.done()  # noqa: SLF001

        state["down"] = False
        await _until(lambda: leader._conn is not None)  # noqa: SLF001
        assert leader.is_leader is True
        assert calls == ["acquired"]
    finally:
        await leader.stop_watching()
        await leader.release()


@pytest.mark.asyncio
async def test_failing_start_callback_does_not_kill_the_watcher() -> None:
    """Błąd przy przejęciu trafia do logu; blokada zostaje, watcher żyje dalej."""
    outcomes: list[str] = []

    async def acquired() -> None:
        outcomes.append("acquired")
        raise RuntimeError("pętle nie wstały")

    async def lost() -> None:
        outcomes.append("lost")

    leader = BackgroundLeader(
        _DSN, on_acquired=acquired, on_lost=lost, lock_key=91_000_007, check_seconds=0.02
    )
    await leader.start()
    try:
        assert leader.is_leader is True
        assert outcomes == ["acquired"]
        await asyncio.sleep(0.1)
        assert leader._watcher is not None and not leader._watcher.done()  # noqa: SLF001
    finally:
        await leader.stop_watching()
        await leader.release()


def test_standby_longer_than_a_rollout_is_reported_as_a_failure() -> None:
    """Pętle stoją, a proces wygląda na zdrowy: to ma otworzyć issue."""
    from app.services.background_task_health import leader_check_value

    assert leader_check_value(is_leader=True, standby_seconds=0) is None
    assert leader_check_value(is_leader=False, standby_seconds=30) == "standby"
    assert leader_check_value(is_leader=False, standby_seconds=301) == (
        "unhealthy: standby 301s — pętle w tle nie działają"
    )


def test_shutdown_releases_the_lock_only_after_loops_stopped() -> None:
    """Następca nie może ruszyć, póki stare pętle jeszcze kończą pracę."""
    source = (_BACKEND / "app/main.py").read_text(encoding="utf-8")
    shutdown = source[source.index("    # Shutdown\n") :]
    watching = shutdown.index("stop_watching()")
    gather = shutdown.index("asyncio.gather(*tasks, return_exceptions=True)")
    release = shutdown.index(".release()")
    dispose = shutdown.index("await engine.dispose()")
    assert watching < gather < release < dispose
