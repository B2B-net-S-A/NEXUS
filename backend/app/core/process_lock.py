"""Blokada między procesem web a workerem.

``asyncio.Lock`` działa w jednym procesie, a ręczne wyzwolenie z trasy i pętla
biegną teraz w dwóch. Blokada doradcza Postgresa na osobnym połączeniu znika razem
z procesem, więc restart kontenera nie zostawia zamurowanej pracy. Przy roli
``all`` (jeden proces) wystarcza ``asyncio.Lock`` wołającego.

Zadanie, które trzyma blokadę, może wejść w nią drugi raz (jak sesja Postgresa):
ręczny start z trasy (``app/core/manual_runs.py``) bierze ją na cały bieg,
a bieg, który bierze ją sam (poczta zamówień, wnioski z notatek), dostaje ``True``.
Inne zadanie, także w tym samym procesie, dostaje ``False``.
"""

from __future__ import annotations

import asyncio
import logging
import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import asyncpg

from app.core.config import settings

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_SECONDS = 5.0

# Zadanie, które w tym procesie trzyma blokadę ``(name, item)``.
_holders: dict[tuple[str, int], asyncio.Task[Any]] = {}


def lock_namespace(name: str) -> int:
    return zlib.crc32(name.encode()) & 0x7FFF_FFFF


@asynccontextmanager
async def cross_process_lock(name: str, item: int = 0) -> AsyncIterator[bool]:
    """``True`` = wyłączność na ``(name, item)``; ``False`` = trzyma ją kto inny."""
    if settings.NEXUS_PROCESS_ROLE == "all":
        yield True
        return
    key = (name, item)
    task = asyncio.current_task()
    if task is not None and _holders.get(key) is task:
        yield True
        return
    conn = await asyncpg.connect(
        settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"),
        timeout=_CONNECT_TIMEOUT_SECONDS,
        server_settings={"application_name": "nexus-process-lock"},
    )
    try:
        owned = bool(
            await conn.fetchval(
                "SELECT pg_try_advisory_lock($1::int, $2::int)",
                lock_namespace(name),
                item,
            )
        )
        if owned and task is not None:
            _holders[key] = task
        try:
            yield owned
        finally:
            if owned and _holders.get(key) is task:
                del _holders[key]
    finally:
        await conn.close()


@asynccontextmanager
async def cross_process_wait_lock(
    name: str, *, timeout_seconds: float
) -> AsyncIterator[bool]:
    """Czekaj na wyłączność na ``name`` najwyżej ``timeout_seconds``.

    Dla kroków, które mają iść po kolei, a nie odpaść (jednorazowe kroki startu
    przy kilku procesach web). ``False`` = brak bazy albo koniec czasu: wołający
    idzie dalej bez blokady, tak jak przed jej wprowadzeniem.
    """
    if settings.NEXUS_PROCESS_ROLE == "all":
        yield True
        return
    conn = None
    acquired = False
    try:
        conn = await asyncpg.connect(
            settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"),
            timeout=_CONNECT_TIMEOUT_SECONDS,
            server_settings={"application_name": "nexus-process-lock"},
        )
        await conn.execute(f"SET lock_timeout = '{int(timeout_seconds * 1000)}ms'")
        await conn.execute("SELECT pg_advisory_lock($1::int, 0)", lock_namespace(name))
        acquired = True
    except (OSError, asyncpg.PostgresError) as exc:
        logger.warning("process lock %s: bez blokady (%s)", name, type(exc).__name__)
    try:
        yield acquired
    finally:
        if conn is not None:
            await conn.close()
