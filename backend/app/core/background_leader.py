"""Jeden właściciel pętli w tle, gdy przy wdrożeniu żyją dwa kontenery.

Rolling update trzyma przez chwilę dwa procesy backendu. Pętle z
``app.state.background_tasks`` nie mają własnego wyboru lidera, więc dwa komplety
to podwójne maile, alerty i importy. Właścicielem jest proces, który trzyma
blokadę doradczą Postgresa na osobnym połączeniu. Następca czeka w ``standby``
i przejmuje pętle, gdy stary proces skończy zamykanie albo zginie, bo Postgres
zwalnia blokadę razem z połączeniem.

Zwykły start bez nakładania zachowuje się jak dawniej: blokada jest wolna, więc
pętle ruszają przed końcem startu. Plan:
``docs/claude/podstawy/przerwa-przy-wdrozeniu.md``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import asyncpg

from app.core.tasks import spawn

logger = logging.getLogger(__name__)

# Blokady doradcze są per baza, więc kopie na stagingu sobie nie przeszkadzają.
BACKGROUND_LEADER_LOCK_KEY = 7_203_411

_CONNECT_TIMEOUT_SECONDS = 5.0
_CHECK_TIMEOUT_SECONDS = 5.0


class BackgroundLeader:
    def __init__(
        self,
        dsn: str,
        *,
        on_acquired: Callable[[], Awaitable[None]],
        on_lost: Callable[[], Awaitable[None]],
        lock_key: int = BACKGROUND_LEADER_LOCK_KEY,
        retry_seconds: float = 1.0,
        check_seconds: float = 5.0,
        connect: Callable[..., Awaitable[Any]] = asyncpg.connect,
    ) -> None:
        self._dsn = dsn
        self._on_acquired = on_acquired
        self._on_lost = on_lost
        self._lock_key = lock_key
        self._retry_seconds = retry_seconds
        self._check_seconds = check_seconds
        self._connect = connect
        self._conn: Any = None
        self._watcher: asyncio.Task[None] | None = None
        self._standby_since = time.monotonic()
        self.is_leader = False

    @property
    def standby_seconds(self) -> int:
        return 0 if self.is_leader else int(time.monotonic() - self._standby_since)

    async def start(self) -> None:
        """Jedna próba przed końcem startu, reszta w tle."""
        await self._try_acquire()
        self._watcher = spawn(self._watch(), "background_leader")

    async def stop_watching(self) -> None:
        """Pierwszy krok zamykania: bez tego przejęcie mogłoby ruszyć pętle w jego trakcie."""
        if self._watcher is not None:
            self._watcher.cancel()
            await asyncio.gather(self._watcher, return_exceptions=True)
            self._watcher = None

    async def release(self) -> None:
        """Dopiero po zatrzymaniu pętli: następca rusza w chwili zamknięcia połączenia."""
        await self._close()
        self.is_leader = False

    async def _watch(self) -> None:
        while True:
            await asyncio.sleep(
                self._check_seconds if self.is_leader else self._retry_seconds
            )
            if not self.is_leader:
                await self._try_acquire()
            elif not await self._lock_connection_alive():
                await self._recover_lost_connection()

    async def _try_acquire(self) -> None:
        if await self._take_lock():
            self.is_leader = True
            logger.info("background leader: przejęto pętle w tle")
            await self._notify(self._on_acquired)

    async def _take_lock(self) -> bool:
        """``True`` = mamy blokadę; zajęta albo brak bazy = ``False``."""
        conn = None
        try:
            conn = await self._connect(
                self._dsn,
                timeout=_CONNECT_TIMEOUT_SECONDS,
                server_settings={"application_name": "nexus-background-leader"},
            )
            if await conn.fetchval("SELECT pg_try_advisory_lock($1)", self._lock_key):
                self._conn = conn
                return True
            await conn.close()
            return False
        except (OSError, asyncpg.PostgresError, asyncio.TimeoutError) as exc:
            logger.warning("background leader: brak odczytu blokady: %r", exc)
            if conn is not None:
                conn.terminate()
            return False

    async def _lock_connection_alive(self) -> bool:
        if self._conn is None:
            return False
        try:
            await asyncio.wait_for(self._conn.fetchval("SELECT 1"), _CHECK_TIMEOUT_SECONDS)
            return True
        except (OSError, asyncpg.PostgresError, asyncpg.InterfaceError, asyncio.TimeoutError):
            return False

    async def _recover_lost_connection(self) -> None:
        """Blokada zniknęła z połączeniem. Pętli nie ruszamy, dopóki nikt jej nie ma."""
        if self._conn is not None:
            self._conn.terminate()
            self._conn = None
        if await self._take_lock():
            logger.warning("background leader: połączenie odnowione, blokada zachowana")
            return
        if await self._lock_held_by_another_process():
            logger.error("background leader: blokadę ma inny proces, zatrzymuję pętle")
            self.is_leader = False
            self._standby_since = time.monotonic()
            await self._notify(self._on_lost)

    async def _lock_held_by_another_process(self) -> bool:
        """Brak bazy to nie utrata: nikt inny też nie wykona pracy, a pętle same ponawiają."""
        conn = None
        try:
            conn = await self._connect(self._dsn, timeout=_CONNECT_TIMEOUT_SECONDS)
            return await conn.fetchval(
                "SELECT count(*) > 0 FROM pg_locks "
                "WHERE locktype = 'advisory' AND objid = $1 AND granted "
                "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())",
                self._lock_key,
            )
        except (OSError, asyncpg.PostgresError, asyncio.TimeoutError):
            return False
        finally:
            if conn is not None:
                await conn.close()

    async def _notify(self, callback: Callable[[], Awaitable[None]]) -> None:
        try:
            await callback()
        except Exception:
            logger.exception("background leader: błąd przy zmianie właściciela pętli")

    async def _close(self) -> None:
        if self._conn is not None:
            try:
                await asyncio.wait_for(self._conn.close(), _CHECK_TIMEOUT_SECONDS)
            except Exception:
                self._conn.terminate()
            self._conn = None
