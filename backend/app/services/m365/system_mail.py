"""Delegated system-mail — powiadomienia systemowe z jednej skrzynki serwisowej
przez ISTNIEJĄCE połączenie M365 (delegated), bez app-only consentu.

Wybiera aktywne ``M365Connection`` dla ``settings.M365_MAIL_SENDER_UPN`` i wysyła
przez ``GraphClient`` (draft + send) — dokładnie ten sam mechanizm co
``m365/sender.send_new`` (rejection-maile), ale **bez** logowania do tabeli
``emails`` / wstrzykiwania podpisu / sprzężenia z kandydatem. To maile systemowe
(deadline-alerty itd.), nie korespondencja kandydacka.

Dzięki temu maile działają zaraz po tym, jak ktoś podłączy skrzynkę
``M365_MAIL_SENDER_UPN`` przez „Połącz Microsoft 365" w Nexusie — nie trzeba
application-permission ``Mail.Send`` ani admin-consentu w Azure (delegated
``Mail.Send`` jest już w ``M365_SCOPES`` i skonsentowany dla istniejących
połączeń).
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.m365 import M365Connection
from app.services.m365.graph_client import GraphClient

logger = logging.getLogger(__name__)


async def get_system_sender_connection(db: AsyncSession) -> Optional[M365Connection]:
    """Aktywne połączenie M365 skrzynki nadawczej (``M365_MAIL_SENDER_UPN``).

    None gdy brak skonfigurowanego UPN-a albo nikt jeszcze nie podłączył tej
    skrzynki w Nexusie. Match po ``mailbox_upn`` case-insensitive; najnowsze.
    """
    upn = (settings.M365_MAIL_SENDER_UPN or "").strip()
    if not upn:
        return None
    return await db.scalar(
        select(M365Connection)
        .where(func.lower(M365Connection.mailbox_upn) == upn.lower())
        .where(M365Connection.is_active.is_(True))
        .order_by(M365Connection.updated_at.desc())
        .limit(1)
    )


async def send_system_email(
    db: AsyncSession,
    connection: M365Connection,
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> bool:
    """Wyślij mail systemowy przez delegated Graph (draft + send). True gdy poszedł.

    Best-effort — nie rzuca; loguje i zwraca bool, żeby outbox (claim/mark) mógł
    zignorować wynik i wznowić w kolejnym przebiegu. HTML gdy podany, inaczej Text.
    """
    if html_body:
        body = {"contentType": "HTML", "content": html_body}
    else:
        body = {"contentType": "Text", "content": text_body}
    payload = {
        "subject": subject,
        "body": body,
        "toRecipients": [{"emailAddress": {"address": to}}],
    }
    try:
        async with GraphClient(connection, db) as gc:
            draft = await gc.post("/me/messages", json=payload)
            message_id = draft.get("id") if isinstance(draft, dict) else None
            if not message_id:
                logger.warning(
                    "system_mail: draft bez id (to=%s subject=%r)", to, subject
                )
                return False
            try:
                await gc.post(f"/me/messages/{message_id}/send", json={})
            except Exception:
                # Wersja robocza już powstała — sprzątnij sierotę z Drafts, żeby
                # nieudane wysyłki nie akumulowały śmieci w skrzynce nadawcy.
                # Potem propaguj błąd do handlera (zwróci False → retry outbox).
                try:
                    await gc.delete(f"/me/messages/{message_id}")
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "system_mail: nie udało się usunąć osieroconego draftu %s",
                        message_id,
                    )
                raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "system_mail send failed to=%s subject=%r error=%s",
            to,
            subject,
            type(exc).__name__,
        )
        return False

    logger.info(
        "system_mail sent to=%s subject=%r via=%s",
        to,
        subject,
        connection.mailbox_upn,
    )
    return True
