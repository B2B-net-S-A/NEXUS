"""Stan M365 po procesie, który właśnie przestał być właścicielem pętli.

Do 03.11.2026 w ``entrypoint.sh``. Przy nakładaniu kontenerów start nowego procesu
nie znaczy, że stary nie żyje, więc reset idzie przy przejęciu pętli
(``app/core/background_leader.py``), czyli po zamknięciu poprzednika.
"""

from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

RESET_RUNNING_SYNC_SQL = (
    "UPDATE m365_connections "
    "SET last_sync_status='idle', "
    "    last_error=COALESCE(last_error, 'reset after container restart') "
    "WHERE last_sync_status='running'"
)

# audyt 22.09 r2 (FIX-07): rezerwacja wysyłki maila przerwana restartem zostawała
# ``pending`` na zawsze: ekran pokazywał „Wysyłanie…", a ponowienie dostawało 409.
# Wynik jest NIEZNANY, więc ``uncertain`` (nigdy „do ponowienia", mail mógł wyjść).
# Minuta zapasu chroni wysyłkę, która właśnie startuje na nowym procesie.
RESET_PENDING_SENDS_SQL = (
    "UPDATE emails SET send_state='uncertain' "
    "WHERE send_state='pending' "
    "AND created_at < now() - interval '1 minute'"
)


async def reset_interrupted_m365_state(conn: AsyncConnection) -> None:
    syncs = await conn.execute(text(RESET_RUNNING_SYNC_SQL))
    pending = await conn.execute(text(RESET_PENDING_SENDS_SQL))
    logger.info(
        "m365 reset: running syncs -> idle %s, pending sends -> uncertain %s",
        syncs.rowcount,
        pending.rowcount,
    )
