"""Maile podpisu w NEXUSIE — ze skrzynki osoby, która wysłała umowę (M365).

Kontraktor zna nadawcę (Sandra, rekruter), więc mail z jego skrzynki budzi
mniej podejrzeń niż systemowy. Bez połączonej skrzynki nic nie wychodzi:
wołający pokazuje link do skopiowania albo zostawia sam dzwonek. Awaria
wysyłki nigdy nie cofa stanu wniosku.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.m365 import M365Connection
from app.services.m365 import sender as m365_sender

logger = logging.getLogger(__name__)

MSG_NO_MAILBOX = "Twoja skrzynka Microsoft 365 nie jest połączona z NEXUSEM."
MSG_FAILED = "Nie udało się wysłać maila — wyślij link sam."


async def mailbox_connected(db: AsyncSession, user_id: int) -> bool:
    connection = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == user_id)
    )
    return bool(connection and connection.is_active)


async def send_from(
    db: AsyncSession,
    *,
    user_id: int | None,
    to: str,
    subject: str,
    body_html: str,
    candidate_id: int | None,
    request_key: str,
) -> tuple[bool, Optional[str]]:
    """(wysłano, powód) — ``request_key`` chroni przed drugą wysyłką przy ponowieniu."""
    if not user_id or not to:
        return False, MSG_NO_MAILBOX
    connection = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == user_id)
    )
    if connection is None or not connection.is_active:
        return False, MSG_NO_MAILBOX
    try:
        await m365_sender.send_new(
            db,
            connection,
            to=[to],
            subject=subject,
            body_html=body_html,
            candidate_id=candidate_id,
            client_request_id=request_key,
            commit_reservation=True,
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — stan wniosku zostaje
        logger.exception("[b2b_esign] mail nie wyszedł key=%s", request_key)
        await db.rollback()
        return False, MSG_FAILED
    return True, None
