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

from app.core.config import settings
from app.models.m365 import (
    Email,
    EmailDirection,
    EmailMatchMethod,
    M365Connection,
)
from app.services.m365.actionable_messages import (
    build_interview_confirmation_card,
)
from app.services.m365.access import require_eligible_connection_owner
from app.services.m365.graph_client import GraphClient
from app.services.m365.html_sanitize import html_to_text, sanitize_html
from app.services.m365.signature_cache import get_outlook_signature

logger = logging.getLogger(__name__)

# Phase 7.7 — visible divider between body and pulled signature so it's
# obvious in the rendered mail where the user's signature begins. The
# class hook lets the frontend (and our future inline editor) collapse
# the block if needed.
_SIGNATURE_DIVIDER = '<br><br><div class="nexus-signature">--</div>'


def _append_signature(body_html: str, signature_html: str) -> str:
    """Concat signature onto a body separated by a visible divider."""
    return body_html + _SIGNATURE_DIVIDER + signature_html


# Outlook treats this header as the "this message has Actionable Messages"
# signal — without it the JSON-LD `OpenAction` block is ignored and the user
# only sees the fallback link.
_ACTIONABLE_MESSAGE_HEADER = "X-MS-Actionable-Message"


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
    await require_eligible_connection_owner(db, connection)
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

    async with GraphClient(connection, db) as gc:
        # Phase 7.7 — append the user's Outlook signature so NEXUS-sent mail
        # matches what they'd get from Outlook itself. Memoized for 24h per
        # mailbox; failures are silent (no signature is better than no send).
        if settings.M365_SIGNATURE_INJECTION_ENABLED:
            signature_html = await get_outlook_signature(
                gc,
                user_id=connection.user_id,
                mailbox_upn=connection.mailbox_upn,
            )
            if signature_html:
                body_html = _append_signature(body_html, sanitize_html(signature_html))
                body_text = html_to_text(body_html)

        payload = {
            "subject": subject,
            "body": {"contentType": "HTML", "content": body_html},
            "toRecipients": [{"emailAddress": {"address": a}} for a in to],
            "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
        }

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


async def send_interview_invitation(
    db: AsyncSession,
    connection: M365Connection,
    *,
    to: list[str],
    cc: Optional[list[str]] = None,
    subject: str,
    body_html: str,
    candidate_id: int,
    event_id: int,
    button_label: str = "Potwierdzam interview",
) -> Email:
    """Send an interview invite enriched with an Outlook Actionable Messages
    "Confirm" button (Phase 7.5).

    The `body_html` is rendered as the recruiter wrote it (signature, agenda,
    etc.) and the JSON-LD action block plus a fallback link are injected
    immediately before send. The `X-MS-Actionable-Message` internet header is
    set on the Graph payload so Outlook recognises the message as actionable.

    Idempotency follows the same fingerprint as `send_new` — a frontend
    double-click within the same minute returns the previously persisted row
    instead of issuing a second Graph POST and a second JWT token.
    """
    await require_eligible_connection_owner(db, connection)
    cc = cc or []

    # Sanitize the recruiter-authored body first (XSS hardening for whatever
    # the user pasted into the editor). Then concatenate our trusted
    # actionable block — it includes the JSON-LD `<script type="application/
    # ld+json">` that bleach would otherwise strip. The block is built from
    # internal-only inputs (event_id/candidate_id/JWT we just signed) so
    # bypassing sanitize on it is safe.
    safe_body_html = sanitize_html(body_html)
    actionable_html, _payload = build_interview_confirmation_card(
        event_id=event_id,
        candidate_id=candidate_id,
        button_label=button_label,
    )
    enriched_html = f"{safe_body_html}\n{actionable_html}"
    body_text = html_to_text(enriched_html)

    now = datetime.now(timezone.utc)
    idempotency_key = _build_idempotency_key(
        user_id=connection.user_id,
        to=to,
        cc=cc,
        subject=subject,
        now=now,
    )
    existing = await db.scalar(
        select(Email).where(Email.idempotency_key == idempotency_key)
    )
    if existing is not None:
        logger.info(
            "send_interview_invitation: idempotent hit for user_id=%s "
            "subject=%r — returning row %d",
            connection.user_id,
            (subject or "")[:60],
            existing.id,
        )
        return existing

    payload: dict = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": enriched_html},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to],
        "ccRecipients": [{"emailAddress": {"address": a}} for a in cc],
        "internetMessageHeaders": [
            {"name": _ACTIONABLE_MESSAGE_HEADER, "value": "true"},
        ],
    }

    async with GraphClient(connection, db) as gc:
        draft = await gc.post("/me/messages", json=payload)
        message_id = draft["id"]
        conversation_id = draft.get("conversationId") or message_id
        internet_message_id = draft.get("internetMessageId")
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
        body_html=enriched_html,
        body_text=body_text,
        body_preview=body_text[:255] if body_text else None,
        sent_at=now,
        received_at=now,
        direction=EmailDirection.sent,
        has_attachments=False,
        is_read=True,
        match_method=EmailMatchMethod.manual,
        matched_at=now,
        match_confidence=1.0,
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
    await require_eligible_connection_owner(db, connection)
    body_html = sanitize_html(body_html)
    body_text = html_to_text(body_html)

    async with GraphClient(connection, db) as gc:
        # Phase 7.7 — same signature injection as send_new(). createReply
        # auto-quotes the thread but does NOT include the user's signature,
        # so we still need to append it.
        if settings.M365_SIGNATURE_INJECTION_ENABLED:
            signature_html = await get_outlook_signature(
                gc,
                user_id=connection.user_id,
                mailbox_upn=connection.mailbox_upn,
            )
            if signature_html:
                body_html = _append_signature(body_html, sanitize_html(signature_html))
                body_text = html_to_text(body_html)

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
