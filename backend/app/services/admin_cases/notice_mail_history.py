"""Poczta kontraktu: maile ze spraw przy kontrakcie i z archiwum administracja@.

Archiwum home.pl (5 875 maili do 20.11.2026) wchodzi skryptem
``scripts/import_admin_mail_archive.py`` do ``archived_mails``, bez zakładania
spraw (decyzja Artura z 23.11.2026). Tu oba źródła składają się w jedną listę
od najnowszego. Treść tylko dla osób, które widzą kwoty klienta.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin_case import AdminCase, AdminCaseMessage
from app.models.notice_mail import ArchivedMail
from app.models.user import User
from app.services.admin_cases import service as cases
from app.services.admin_cases import notice_rules as rules

EXCERPT_LIMIT = 600


def _excerpt(body: str) -> str:
    return rules.fresh_text(body or "").strip()[:EXCERPT_LIMIT]


async def contract_mail_feed(
    db: AsyncSession, contract_id: int, *, user: User, with_body: bool, limit: int
) -> list[dict[str, Any]]:
    """Wiadomości spraw tylko dla osób, które czytają sprawę (``cases.may_read``):
    do kontraktu przypinają się też sprawy kadrowe i odejścia, więc sam dostęp
    do kontraktu nie wystarcza nawet na temat i nadawcę."""

    case_rows = [
        (message, case.id, case.title)
        for message, case in (
            await db.execute(
                select(AdminCaseMessage, AdminCase)
                .join(AdminCase, AdminCase.id == AdminCaseMessage.case_id)
                .where(AdminCase.contract_id == contract_id)
                .order_by(AdminCaseMessage.received_at.desc().nulls_last())
                .limit(limit)
            )
        ).all()
        if cases.may_read(user, case)
    ]
    # Archiwum to skrzynka administracja@ (także kadry i odejścia), więc widzi je
    # tylko obsługa spraw — ta sama zasada co przy wiadomościach w sprawach.
    archived = (
        []
        if not cases.is_handler(user)
        else (
            await db.scalars(
                select(ArchivedMail)
                .where(ArchivedMail.contract_id == contract_id)
                .order_by(ArchivedMail.received_at.desc().nulls_last())
                .limit(limit)
            )
        ).all()
    )
    feed: list[dict[str, Any]] = [
        {
            "key": f"case-message:{message.id}",
            "source": "case",
            "received_at": message.received_at,
            "sender": message.sender_name or message.sender_email,
            "subject": message.subject,
            "direction": message.direction,
            "case_id": case_id,
            "case_title": case_title,
            "attachments": len(
                [a for a in (message.attachments or []) if not a.get("inline")]
            ),
            "excerpt": _excerpt(message.body_text) if with_body else None,
        }
        for message, case_id, case_title in case_rows
    ]
    # Ten sam mail bywa w sprawie (czytnik od 18.11) i w archiwum home.pl (do 20.11).
    seen_ids = {
        message.internet_message_id
        for message, _, _ in case_rows
        if message.internet_message_id
    }
    feed += [
        {
            "key": f"archive:{mail.id}",
            "source": "archive",
            "received_at": mail.received_at,
            "sender": mail.sender_name or mail.sender_email,
            "subject": mail.subject,
            "direction": "out" if mail.folder.upper().startswith("SENT") else "in",
            "case_id": None,
            "case_title": None,
            "attachments": len(mail.attachments or []),
            "excerpt": _excerpt(mail.body_text) if with_body else None,
        }
        for mail in archived
        if not (mail.message_id and mail.message_id in seen_ids)
    ]
    feed.sort(
        key=lambda item: item["received_at"].timestamp() if item["received_at"] else 0,
        reverse=True,
    )
    return feed[:limit]
