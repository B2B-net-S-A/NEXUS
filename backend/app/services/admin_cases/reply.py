"""Odpowiedź ze sprawy: mail wychodzi z wątku klienta, ze skrzynki sprawy.

Reader czyta później tę samą wiadomość jako „własny mail” (``mail_ingest``), więc
odpowiedź nie zakłada nowej sprawy ani nie otwiera zamkniętej. Wysyła człowiek
kliknięciem; bez skonfigurowanej skrzynki trasa odmawia, zamiast udawać sukces.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_case import AdminCase, AdminCaseMessage
from app.models.user import User
from app.services.admin_cases import mailbox
from app.services.admin_cases.service import CaseError
from app.services.hr import audit

logger = logging.getLogger(__name__)

REPLY_MAX = 10_000


class ReplyTransport(Protocol):
    async def reply(self, mailbox_upn: str, message_id: str, text: str) -> None: ...


class GraphReplyTransport:
    """``POST /users/{upn}/messages/{id}/reply``: Graph trzyma wątek i Wysłane."""

    async def reply(self, mailbox_upn: str, message_id: str, text: str) -> None:
        from app.services.hr.m365.auth import acquire_hr_token  # noqa: PLC0415
        from app.services.m365.app_graph_client import AppGraphClient  # noqa: PLC0415

        async with AppGraphClient(token_provider=acquire_hr_token) as client:
            await client.post(
                f"/users/{mailbox_upn}/messages/{quote(message_id, safe='')}/reply",
                json={"comment": text},
            )


async def _latest_inbound(db: AsyncSession, case_id: int) -> Optional[AdminCaseMessage]:
    return await db.scalar(
        select(AdminCaseMessage)
        .where(
            AdminCaseMessage.case_id == case_id,
            AdminCaseMessage.direction == "in",
        )
        .order_by(
            AdminCaseMessage.received_at.desc().nulls_last(), AdminCaseMessage.id.desc()
        )
        .limit(1)
    )


async def send_reply(
    db: AsyncSession,
    case: AdminCase,
    *,
    actor: User,
    body: str,
    transport: Optional[ReplyTransport] = None,
) -> AdminCaseMessage:
    text_value = (body or "").replace("\x00", "").strip()
    if not text_value:
        raise CaseError("Odpowiedź nie może być pusta.")
    if len(text_value) > REPLY_MAX:
        raise CaseError(f"Odpowiedź może mieć najwyżej {REPLY_MAX} znaków.")
    upn = mailbox.m365_mailbox()
    if not upn:
        raise CaseError("Skrzynka spraw nie jest jeszcze ustawiona.")
    inbound = await _latest_inbound(db, case.id)
    if inbound is None:
        raise CaseError("Ta sprawa nie ma maila, na który można odpowiedzieć.")
    sender = transport or GraphReplyTransport()
    try:
        await sender.reply(upn, inbound.graph_message_id, text_value)
    except Exception as exc:  # noqa: BLE001 — komunikat dla człowieka, szczegół w logu
        logger.warning("admin_cases_reply: wysyłka nieudana (%s)", type(exc).__name__)
        raise CaseError(
            "Nie udało się wysłać odpowiedzi. Sprawdź połączenie ze skrzynką i spróbuj ponownie."
        ) from exc
    now = datetime.now(timezone.utc)
    sent: dict[str, Any] = {
        "case_id": case.id,
        "graph_message_id": f"sent:{uuid.uuid4().hex}",
        "conversation_id": inbound.conversation_id,
        "sender_email": upn,
        "sender_name": actor.name,
        "subject": inbound.subject,
        "received_at": now,
        "body_text": text_value,
        "attachments": [],
        "direction": "out",
    }
    message = AdminCaseMessage(**sent)
    db.add(message)
    case.updated_at = now
    await db.flush()
    # Treść odpowiedzi zostaje w sprawie, ślad niesie same identyfikatory.
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=case.subject_user_id,
        entity_type="admin_case",
        entity_id=case.id,
        action="case_replied",
        details={"message_id": message.id},
    )
    return message
