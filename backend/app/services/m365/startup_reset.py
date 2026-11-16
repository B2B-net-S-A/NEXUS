"""Stan M365 po procesie, który przestał istnieć w połowie pracy.

Do 03.11.2026 w ``entrypoint.sh``, potem przy przejęciu pętli. Od etapu B2
(web i worker jako osobne aplikacje z rolling update) żaden start nie znaczy,
że poprzednik nie żyje: nowy web wstaje, gdy stary jeszcze obsługuje żądania,
a worker przejmuje pętle, gdy nowy web już wysyła maile. Dlatego reset nie
zgaduje po chwili startu, tylko po stanie, który żywy proces na pewno trzyma:

* przebieg synchronizacji trzyma blokadę ``cross_process_lock("m365_sync", id)``,
  więc ``running`` bez tej blokady to przebieg porzucony;
* wysyłka trwa najwyżej kilka wywołań Graph po ``_HARD_TIMEOUT_SECONDS`` (120 s),
  więc ``pending`` starsza niż ``PENDING_SEND_MARGIN`` nie ma już właściciela.

Pętla ``m365_interrupted_reset`` biegnie w workerze, także po tym, jak web
zginął między wdrożeniami.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.process_lock import lock_namespace

logger = logging.getLogger(__name__)

#: Zapas ponad najdłuższą wysyłkę (szkic + załączniki + send, po 120 s każde).
PENDING_SEND_MARGIN_MINUTES = 15
#: Co tyle sprawdza pętla: porzucona wysyłka wisi najwyżej margines + interwał.
INTERVAL_SECONDS = 300

# `pg_try_advisory_xact_lock` z tą samą parą kluczy co `cross_process_lock`:
# blokada zajęta = przebieg żyje w innym procesie, wiersz zostaje. Blokada
# transakcyjna znika z końcem tej transakcji.
RESET_RUNNING_SYNC_SQL = (
    "UPDATE m365_connections "
    "SET last_sync_status='idle', "
    "    last_error=COALESCE(last_error, 'reset after container restart') "
    "WHERE last_sync_status='running' "
    "AND pg_try_advisory_xact_lock(CAST(:lock_ns AS int), id)"
)

# audyt 22.09 r2 (FIX-07): rezerwacja wysyłki maila przerwana restartem zostawała
# ``pending`` na zawsze: ekran pokazywał „Wysyłanie…", a ponowienie dostawało 409.
# Wynik jest NIEZNANY, więc ``uncertain`` (nigdy „do ponowienia", mail mógł wyjść).
RESET_PENDING_SENDS_SQL = (
    "UPDATE emails SET send_state='uncertain' "
    "WHERE send_state='pending' "
    f"AND created_at < now() - interval '{PENDING_SEND_MARGIN_MINUTES} minutes'"
)


async def reset_interrupted_m365_state(conn: AsyncConnection) -> None:
    syncs = await conn.execute(
        text(RESET_RUNNING_SYNC_SQL), {"lock_ns": lock_namespace("m365_sync")}
    )
    pending = await conn.execute(text(RESET_PENDING_SENDS_SQL))
    if syncs.rowcount or pending.rowcount:
        logger.info(
            "m365 reset: running syncs -> idle %s, pending sends -> uncertain %s",
            syncs.rowcount,
            pending.rowcount,
        )


async def m365_interrupted_reset_loop() -> None:
    """Pętla tła w workerze — rejestrowana w lifespanie ``main.py``."""
    from app.core.database import engine

    while True:
        try:
            async with engine.begin() as conn:
                await reset_interrupted_m365_state(conn)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — następny przebieg za INTERVAL_SECONDS
            logger.exception("m365 reset: przebieg padł")
        await asyncio.sleep(INTERVAL_SECONDS)
