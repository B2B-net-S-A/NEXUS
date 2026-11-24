"""Ręczne przebiegi uruchamiane z tras — jeden naraz w całym backendzie.

Flagę ``running`` i postęp biegu w pamięci widzi tylko proces, który bieg
uruchomił. Przy dwóch procesach web (``docs/claude/podstawy/kilka-procesow-web.md``)
status z drugiego procesu mówił „nie biegnie” albo 404, a drugi start szedł
równolegle z pierwszym.

* ``start_exclusive`` bierze blokadę doradczą (``cross_process_lock``) w zadaniu
  biegu i trzyma ją do końca biegu. Trasa czeka tylko na próbę blokady:
  ``False`` = bieg już trwa (tu, w drugim procesie web albo w workerze), trasa
  oddaje 409 i nic nie startuje. Rezerwacja w tym procesie stoi, zanim trasa
  odda pętlę, więc dwa szybkie POST-y dają jeden bieg także w roli ``all``,
  gdzie blokady doradczej nie ma.
* ``is_running`` czyta ``pg_locks``, więc widzi bieg z każdego procesu, a po
  procesie, który padł, blokady już nie ma i status nie zostaje na „trwa”.
* Postęp, który ma być widać z drugiego procesu, bieg zapisuje w ``app_settings``
  (``save_snapshot``, ``publishing``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.process_lock import cross_process_lock, lock_namespace
from app.core.tasks import spawn

logger = logging.getLogger(__name__)

# Biegi uruchomione w tym procesie, od startu do końca.
_reserved: set[str] = set()

# Blokada z dwóch kluczy int4 ma w `pg_locks` pierwszy klucz w `classid`, drugi
# w `objid` i `objsubid = 2` (dokumentacja Postgresa, „Advisory Locks”).
_LOCK_HELD_SQL = text(
    "SELECT EXISTS (SELECT 1 FROM pg_locks"
    " WHERE locktype = 'advisory' AND granted AND objsubid = 2"
    " AND database = (SELECT oid FROM pg_database"
    " WHERE datname = current_database())"
    " AND classid = CAST(CAST(:ns AS integer) AS oid)"
    " AND objid = CAST(CAST(:item AS integer) AS oid))"
)

_UPSERT_SQL = text(
    "INSERT INTO app_settings (key, value) VALUES (:key, CAST(:value AS jsonb)) "
    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
)


def running_here(name: str) -> bool:
    """Bieg ``name`` uruchomiony w tym procesie jeszcze trwa."""
    return name in _reserved


def _keep_exception_quiet(future: asyncio.Future[bool]) -> None:
    # Trasa, którą przerwano w trakcie czekania, nie odbierze błędu próby blokady
    # (jest w logu zadania), więc asyncio nie loguje go drugi raz.
    if not future.cancelled():
        future.exception()


async def start_exclusive(
    name: str, run: Callable[[], Awaitable[Any]], *, label: str
) -> bool:
    """Uruchom ``run()`` w tle pod blokadą ``name``; ``False`` = bieg już trwa."""
    if name in _reserved:
        return False
    _reserved.add(name)
    acquired: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
    acquired.add_done_callback(_keep_exception_quiet)

    async def runner() -> None:
        try:
            async with cross_process_lock(name) as owned:
                if not acquired.done():
                    acquired.set_result(owned)
                if owned:
                    await run()
        except BaseException as exc:
            if not acquired.done():
                acquired.set_exception(
                    exc
                    if isinstance(exc, Exception)
                    else RuntimeError(f"{label}: bieg przerwany przed startem")
                )
            raise
        finally:
            _reserved.discard(name)

    try:
        spawn(runner(), label)
    except BaseException:
        _reserved.discard(name)
        raise
    return await asyncio.shield(acquired)


async def lock_held(name: str, *, db: Optional[AsyncSession] = None) -> bool:
    """Blokadę ``cross_process_lock(name)`` trzyma jakieś połączenie z bazą."""
    params = {"ns": lock_namespace(name), "item": 0}
    if db is not None:
        return bool(await db.scalar(_LOCK_HELD_SQL, params))
    async with AsyncSessionLocal() as session:
        return bool(await session.scalar(_LOCK_HELD_SQL, params))


async def is_running(name: str, *, db: Optional[AsyncSession] = None) -> bool:
    """Czy bieg ``name`` trwa w tym albo w innym procesie (drugi web, worker)."""
    if name in _reserved:
        return True
    if settings.NEXUS_PROCESS_ROLE == "all":
        return False
    return await lock_held(name, db=db)


async def save_snapshot(key: str, value: dict[str, Any]) -> None:
    """Zapisz stan biegu w ``app_settings``; błąd zapisu nie zatrzymuje biegu."""
    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                _UPSERT_SQL, {"key": key, "value": json.dumps(value, default=str)}
            )
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — zapis stanu nie może zabić biegu
        logger.warning(
            "[manual-run] zapis stanu %s nie powiódł się (%s)",
            key,
            type(exc).__name__,
        )


async def load_snapshot(key: str) -> Optional[dict[str, Any]]:
    """Ostatni zapisany stan biegu albo ``None`` (także gdy odczyt padł)."""
    try:
        async with AsyncSessionLocal() as db:
            value = await db.scalar(
                text("SELECT value FROM app_settings WHERE key = :key"), {"key": key}
            )
    except Exception as exc:  # noqa: BLE001 — status ma działać bez zapisu
        logger.warning(
            "[manual-run] odczyt stanu %s nie powiódł się (%s)",
            key,
            type(exc).__name__,
        )
        return None
    return value if isinstance(value, dict) else None


SNAPSHOT_EVERY_SECONDS = 5.0


@asynccontextmanager
async def publishing(key: str, state: dict[str, Any]) -> AsyncIterator[None]:
    """Zapisuj ``state`` pod ``key`` na starcie, co 5 s i na końcu biegu."""
    await save_snapshot(key, state)
    stop = asyncio.Event()

    async def keep() -> None:
        while not stop.is_set():
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=SNAPSHOT_EVERY_SECONDS)
            if not stop.is_set():
                await save_snapshot(key, state)

    keeper = spawn(keep(), f"{key}_snapshot")
    try:
        yield
    finally:
        stop.set()
        with suppress(Exception):
            await keeper
        await save_snapshot(key, state)


__all__ = [
    "is_running",
    "load_snapshot",
    "lock_held",
    "publishing",
    "running_here",
    "save_snapshot",
    "start_exclusive",
]
