"""Send emails from the user's mailbox via Graph.

Flow for a NEW message:
    POST /me/messages         (create draft → returns id + internetMessageId)
    POST /me/messages/{id}/send   (send; 202 Accepted)

We use the draft+send flow (not /me/sendMail) because:
- It returns the message id pre-send, so we can persist a local row without
  polling SentItems.
- It lets us attach files before sending without a second round trip.

Flow for a REPLY:
    POST /me/messages/{id}/reply   (Graph auto-quotes the thread)

Phase 2.6 — `send_new` is idempotent against double-submit. The caller's
intent is fingerprinted as `sha256(user_id|sorted_recipients|subject|minute_bucket)`
and stored in `emails.idempotency_key`. A repeat within the same minute
returns the cached row instead of issuing a duplicate Graph POST.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.m365 import (
    Email,
    EmailDirection,
    EmailMatchMethod,
    M365Connection,
)
from app.services.m365.graph_client import GraphClient
from app.services.m365.html_sanitize import html_to_text, sanitize_html

logger = logging.getLogger(__name__)


def _build_idempotency_key(
    *,
    user_id: int,
    to: list[str],
    cc: list[str],
    subject: str,
    now: Optional[datetime] = None,
) -> str:
    """Phase 2.6 — fingerprint a send intent for deduplication.

    Within the same minute, the SAME (user, recipients, subject) tuple yields
    the SAME key — so a network retry from the frontend (or a refreshed tab)
    won't trigger a second Graph POST. Recipients are normalized (lowercase,
    sorted) so case/order differences don't break the match.
    """
    now = now or datetime.now(timezone.utc)
    minute_bucket = now.strftime("%Y-%m-%dT%H:%M")
    normalized = "|".join(
        [
            str(user_id),
            ",".join(sorted({a.strip().lower() for a in to if a})),
            ",".join(sorted({a.strip().lower() for a in cc if a})),
            (subject or "").strip(),
            minute_bucket,
        ]
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


async def send_new(
    db: AsyncSession,
    connection: M365Connection,
    *,
    to: list[str],
    cc: Optional[list[str]] = None,
    subject: str,
    body_html: str,
    candidate_id: Optional[int] = None,
) -> Email:
    """Send a brand-new message from the connected mailbox.

    Returns the persisted local Email row (direction=sent). Phase 2.6 — repeat
    calls with the same (user, recipients, subject) within the same minute
    return the previously-sent row without issuing a duplicate Graph POST.
    """
    cc = cc or []
    body_html = sanitize_html(body_html)
    body_text = html_to_text(body_html)

    now = datetime.now(timezone.utc)
    idempotency_key = _build_idempotency_key(
        user_id=connection.user_id,
        to=to,
        cc=cc,
        subject=subject,
        now=now,
    )
    # Phase 2.6 — short-circuit on duplicate intent (frontend retry, double-
    # click, refreshed tab). The unique partial index on emails.idempotency_key
    # also guards against a race that slips past this read.
    existing = await db.scalar(
        select(Email).where(Email.idempotency_key == idempotency_key)
    )
    if existing is not None:
        logger.info(
            "send_new: idempotent hit for user_id=%s subject=%r — returning row %d",
            connection.user_id,
            (subject or "")[:60],
            existing.id,
        )
        return existing

    payload = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": body_html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to],
        "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
    }

    async with GraphClient(connection, db) as gc:
        # 1) Create draft
        draft = await gc.post("/me/messages", json=payload)
        message_id = draft["id"]
        conversation_id = draft.get("conversationId") or message_id
        internet_message_id = draft.get("internetMessageId")
        # 2) Send
        await gc.post(f"/me/messages/{message_id}/send", json={})

    row = Email(
        user_id=connection.user_id,
        candidate_id=candidate_id,
        m365_message_id=message_id,
        m365_internet_message_id=internet_message_id,
        m365_conversation_id=conversation_id,
        subject=subject[:998] if subject else None,
        from_address=connection.mailbox_upn,
        from_name=None,
        to_addresses=[{"address": a} for a in to],
        cc_addresses=[{"address": a} for a in cc],
        body_html=body_html,
        body_text=body_text,
        body_preview=body_text[:255] if body_text else None,
        sent_at=now,
        received_at=now,
        direction=EmailDirection.sent,
        has_attachments=False,
        is_read=True,
        match_method=(
            EmailMatchMethod.manual
            if candidate_id is not None
            else EmailMatchMethod.unmatched
        ),
        matched_at=now if candidate_id is not None else None,
        match_confidence=1.0 if candidate_id is not None else None,
        idempotency_key=idempotency_key,
    )
    db.add(row)
    await db.flush()
    return row


async def reply(
    db: AsyncSession,
    connection: M365Connection,
    *,
    email_row: Email,
    body_html: str,
) -> Email:
    """Reply to an existing message; Graph auto-quotes thread history.

    Returns the persisted local Email row for the sent reply. The reply's
    Graph id is resolved from the draft flow (the /reply endpoint returns 202
    without a body, so we use /createReply → /send for the id).
    """
    body_html = sanitize_html(body_html)
    body_text = html_to_text(body_html)

    async with GraphClient(connection, db) as gc:
        # 1) Create reply draft (Graph fills in recipients, subject, thread history).
        draft = await gc.post(
            f"/me/messages/{email_row.m365_message_id}/createReply", json={}
        )
        draft_id = draft["id"]
        # 2) Patch the body.
        await gc.patch(
            f"/me/messages/{draft_id}",
            json={"body": {"contentType": "HTML", "content": body_html}},
        )
        # 3) Send.
        await gc.post(f"/me/messages/{draft_id}/send", json={})

    now = datetime.now(timezone.utc)
    row = Email(
        user_id=connection.user_id,
        candidate_id=email_row.candidate_id,
        m365_message_id=draft_id,
        m365_conversation_id=email_row.m365_conversation_id,
        subject=(
            f"Re: {email_row.subject}"
            if email_row.subject and not email_row.subject.lower().startswith("re:")
            else email_row.subject or "Re:"
        )[:998],
        from_address=connection.mailbox_upn,
        to_addresses=[{"address": email_row.from_address}],
        cc_addresses=[],
        body_html=body_html,
        body_text=body_text,
        body_preview=body_text[:255] if body_text else None,
        sent_at=now,
        received_at=now,
        direction=EmailDirection.sent,
        has_attachments=False,
        is_read=True,
        match_method=(
            EmailMatchMethod.manual
            if email_row.candidate_id is not None
            else EmailMatchMethod.unmatched
        ),
        matched_at=now if email_row.candidate_id is not None else None,
        match_confidence=1.0 if email_row.candidate_id is not None else None,
    )
    db.add(row)
    await db.flush()
    return row
