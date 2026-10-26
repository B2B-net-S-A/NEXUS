"""Maile podpisu w NEXUSIE — ze skrzynki osoby, która wysłała umowę (M365).

Kontraktor zna nadawcę (Sandra, rekruter), więc mail z jego skrzynki budzi
mniej podejrzeń niż systemowy. Bez połączonej skrzynki nic nie wychodzi:
wołający pokazuje link do skopiowania albo zostawia sam dzwonek. Awaria
wysyłki nigdy nie cofa stanu wniosku.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_config
from app.models.m365 import M365Connection
from app.services.m365 import sender as m365_sender

logger = logging.getLogger(__name__)

MSG_NO_MAILBOX = "Twoja skrzynka Microsoft 365 nie jest połączona z NEXUSEM."
MSG_FAILED = "Nie udało się wysłać maila — wyślij link sam."

_WARSAW = ZoneInfo("Europe/Warsaw")
REGISTER_PATH = "/contracts/b2b-generator?tab=generated"


def company_signer_message(
    *, number: str, contractor_name: str, since: datetime, reminder: bool
) -> tuple[str, str]:
    """(temat, treść) maila do osoby, która podpisuje za B2B Network.

    Olaf 26.10.2026: „nic mi nie przyszło” — był tylko dzwonek bez ikony."""
    link = f"{app_config.PUBLIC_BASE_URL.rstrip('/')}{REGISTER_PATH}"
    who = html.escape(contractor_name)
    num = html.escape(number)
    if reminder:
        subject = f"Przypomnienie: umowa B2B {number} nadal czeka na Twój podpis"
        lead = (
            f"umowa B2B nr {num} ({who}) od "
            f"{since.astimezone(_WARSAW):%d.%m.%Y} czeka na podpis za B2B Network. "
            "Kontraktor ma już swój podpis."
        )
    else:
        subject = f"Umowa B2B {number} czeka na Twój podpis"
        lead = (
            f"{who} podpisał(a) umowę B2B nr {num} podpisem kwalifikowanym. "
            "Brakuje podpisu za B2B Network."
        )
    body = (
        f"<p>Dzień dobry,</p><p>{lead}</p>"
        "<p>Pobierz plik w NEXUSIE, podpisz go swoim podpisem kwalifikowanym "
        "w pliku PDF (PAdES) i wgraj z powrotem.</p>"
        f'<p><a href="{html.escape(link)}">Otwórz umowę w NEXUSIE</a></p>'
    )
    return subject, body


def contractor_copy_message(*, number: str, contractor_name: str) -> tuple[str, str]:
    """(temat, treść) maila z umową podpisaną przez obie strony (26.10.2026)."""
    subject = f"Umowa B2B {number} podpisana przez obie strony"
    body = (
        f"<p>Dzień dobry {html.escape(contractor_name)},</p>"
        f"<p>w załączniku umowa B2B nr {html.escape(number)} podpisana przez "
        "Ciebie i przez B2B Network. To Twój egzemplarz, zachowaj go.</p>"
        "<p>Pozdrawiamy<br>B2B Network</p>"
    )
    return subject, body


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
    attachments: Sequence[m365_sender.FileAttachment] = (),
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
            attachments=attachments,
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — stan wniosku zostaje
        logger.exception("[b2b_esign] mail nie wyszedł key=%s", request_key)
        await db.rollback()
        return False, MSG_FAILED
    return True, None
