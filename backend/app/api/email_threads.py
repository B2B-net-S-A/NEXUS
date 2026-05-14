"""Email thread endpoints used by the candidate-detail UI.

GET  /api/candidates/{id}/emails          → list conversations (grouped)
GET  /api/emails/{id}                     → full email w/ attachments
GET  /api/emails/{id}/attachments/{aid}/download → binary
POST /api/candidates/{id}/emails/compose  → new email in candidate context
POST /api/candidates/{id}/emails/reply    → reply to an existing email
POST /api/microsoft365/emails/bulk        → bulk action on selected emails (Phase 5.1)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.candidate import Candidate
from app.models.m365 import (
    Email,
    EmailAttachment,
    EmailMatchMethod,
    M365Connection,
)
from app.services.m365 import sender as m365_sender
from app.services.m365.attachment_handler import STORAGE_ROOT

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────────────


class AttachmentOut(BaseModel):
    id: int
    filename: str
    content_type: str
    size_bytes: int
    is_inline: bool

    model_config = ConfigDict(from_attributes=True)


class EmailOut(BaseModel):
    id: int
    m365_message_id: str
    m365_conversation_id: str
    subject: Optional[str]
    from_address: str
    from_name: Optional[str]
    to_addresses: list[dict] = []
    cc_addresses: list[dict] = []
    body_html: Optional[str]
    body_text: Optional[str]
    body_preview: Optional[str]
    sent_at: Optional[datetime]
    received_at: datetime
    direction: str
    has_attachments: bool
    is_read: bool
    is_archived: bool
    is_private_filtered: bool
    match_method: str
    match_confidence: Optional[float]
    candidate_id: Optional[int] = None
    attachments: list[AttachmentOut] = []

    model_config = ConfigDict(from_attributes=True)


class ThreadPreview(BaseModel):
    conversation_id: str
    subject: Optional[str]
    latest: EmailOut
    message_count: int
    unread_count: int


class ComposeRequest(BaseModel):
    to: list[EmailStr]
    cc: list[EmailStr] = []
    subject: str = Field(min_length=1, max_length=998)
    body_html: str = Field(min_length=1)


class ReplyRequest(BaseModel):
    email_id: int
    body_html: str = Field(min_length=1)


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _require_active_connection(db: AsyncSession, user_id: int) -> M365Connection:
    conn = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == user_id)
    )
    if conn is None or not conn.is_active:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED,
            detail="No active Microsoft 365 connection",
        )
    return conn


def _can_access_email(email: Email, user, privileged_role: bool) -> bool:
    if email.user_id == user.id:
        return True
    return privileged_role


def _to_email_out(email: Email) -> EmailOut:
    return EmailOut(
        id=email.id,
        m365_message_id=email.m365_message_id,
        m365_conversation_id=email.m365_conversation_id,
        subject=email.subject,
        from_address=email.from_address,
        from_name=email.from_name,
        to_addresses=list(email.to_addresses or []),
        cc_addresses=list(email.cc_addresses or []),
        body_html=email.body_html,
        body_text=email.body_text,
        body_preview=email.body_preview,
        sent_at=email.sent_at,
        received_at=email.received_at,
        direction=email.direction.value if email.direction else "received",
        has_attachments=email.has_attachments,
        is_read=email.is_read,
        is_archived=email.is_archived,
        is_private_filtered=email.is_private_filtered,
        match_method=email.match_method.value if email.match_method else "unmatched",
        match_confidence=email.match_confidence,
        candidate_id=email.candidate_id,
        attachments=[],  # filled by callers that eager-load
    )


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/candidates/{candidate_id}/emails", response_model=list[ThreadPreview])
async def list_candidate_emails(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    include_archived: bool = Query(False),
) -> list[ThreadPreview]:
    """Return conversation previews for a candidate, most-recent first.

    Groups by `m365_conversation_id`. Each preview carries the latest message
    plus aggregate counts (total + unread). Archived emails (Phase 5.1) are
    hidden unless `include_archived=true`.
    """
    # Fetch all candidate emails the user can see, latest first.
    base_stmt = select(Email).where(Email.candidate_id == candidate_id)
    if not include_archived:
        base_stmt = base_stmt.where(Email.is_archived.is_(False))
    base_stmt = (
        base_stmt.order_by(Email.received_at.desc()).limit(
            1000
        )  # cap for safety — UI paginates by thread count
    )
    result = await db.execute(base_stmt)
    rows = result.scalars().all()

    privileged = current_user.role.value in {"admin", "delivery_lead"}
    visible = [e for e in rows if _can_access_email(e, current_user, privileged)]

    threads: dict[str, dict] = {}
    for e in visible:
        conv = e.m365_conversation_id
        slot = threads.get(conv)
        if slot is None:
            threads[conv] = {"latest": e, "count": 1, "unread": 0 if e.is_read else 1}
        else:
            slot["count"] += 1
            if not e.is_read:
                slot["unread"] += 1
            if e.received_at > slot["latest"].received_at:
                slot["latest"] = e

    previews = sorted(
        threads.values(), key=lambda t: t["latest"].received_at, reverse=True
    )[:limit]

    return [
        ThreadPreview(
            conversation_id=t["latest"].m365_conversation_id,
            subject=t["latest"].subject,
            latest=_to_email_out(t["latest"]),
            message_count=t["count"],
            unread_count=t["unread"],
        )
        for t in previews
    ]


@router.get("/emails/{email_id}", response_model=EmailOut)
async def get_email(
    email_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> EmailOut:
    email = await db.get(Email, email_id)
    if email is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "email not found")
    privileged = current_user.role.value in {"admin", "delivery_lead"}
    if not _can_access_email(email, current_user, privileged):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    # Separate attachment query — avoid assigning into the SA relationship
    # collection, which could trip cascade behavior.
    atts_result = await db.scalars(
        select(EmailAttachment).where(EmailAttachment.email_id == email_id)
    )
    attachments = [AttachmentOut.model_validate(a) for a in atts_result.all()]
    out = _to_email_out(email)
    out.attachments = attachments
    return out


@router.get("/emails/{email_id}/attachments/{attachment_id}/download")
async def download_attachment(
    email_id: int,
    attachment_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    email = await db.get(Email, email_id)
    att = await db.get(EmailAttachment, attachment_id)
    if email is None or att is None or att.email_id != email.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "attachment not found")
    privileged = current_user.role.value in {"admin", "delivery_lead"}
    if not _can_access_email(email, current_user, privileged):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    if not att.storage_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file not persisted")
    abs_path = (STORAGE_ROOT / att.storage_path).resolve()
    # Path-traversal guard — same as storage_service.get_contract_document_path.
    try:
        abs_path.relative_to(STORAGE_ROOT.resolve())
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid path")
    if not abs_path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "file missing on disk")
    return FileResponse(abs_path, media_type=att.content_type, filename=att.filename)


@router.post("/candidates/{candidate_id}/emails/compose", response_model=EmailOut)
async def compose_email(
    candidate_id: int,
    payload: ComposeRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> EmailOut:
    conn = await _require_active_connection(db, current_user.id)
    row = await m365_sender.send_new(
        db,
        conn,
        to=[str(x) for x in payload.to],
        cc=[str(x) for x in payload.cc],
        subject=payload.subject,
        body_html=payload.body_html,
        candidate_id=candidate_id,
    )
    await db.commit()
    return _to_email_out(row)


@router.post("/candidates/{candidate_id}/emails/reply", response_model=EmailOut)
async def reply_email(
    candidate_id: int,
    payload: ReplyRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> EmailOut:
    conn = await _require_active_connection(db, current_user.id)
    original = await db.get(Email, payload.email_id)
    if original is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "original email not found")
    if original.user_id != current_user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "forbidden")
    if original.candidate_id not in (None, candidate_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "original email belongs to a different candidate",
        )
    row = await m365_sender.reply(
        db, conn, email_row=original, body_html=payload.body_html
    )
    if row.candidate_id is None:
        row.candidate_id = candidate_id
        row.match_method = EmailMatchMethod.manual
    await db.commit()
    return _to_email_out(row)


# ── Bulk actions (Phase 5.1) ────────────────────────────────────────────────


BulkEmailAction = Literal[
    "archive",
    "mark_read",
    "mark_unread",
    "link_to_candidate",
    "unlink",
]


class BulkEmailActionRequest(BaseModel):
    """Request shape for POST /api/microsoft365/emails/bulk.

    `candidate_id` is required only for `link_to_candidate` — validated below.
    """

    email_ids: list[int] = Field(..., min_length=1, max_length=200)
    action: BulkEmailAction
    candidate_id: Optional[int] = None

    @model_validator(mode="after")
    def _check_candidate_for_link(self) -> "BulkEmailActionRequest":
        if self.action == "link_to_candidate" and self.candidate_id is None:
            raise ValueError("candidate_id is required for action='link_to_candidate'")
        return self


class BulkEmailActionItemError(BaseModel):
    id: int
    reason: str


class BulkEmailActionResponse(BaseModel):
    action: BulkEmailAction
    updated_count: int
    skipped_count: int
    errors: list[BulkEmailActionItemError]


def _apply_bulk_action(
    email: Email,
    action: BulkEmailAction,
    candidate_id: Optional[int],
    user_id: int,
    now: datetime,
) -> None:
    if action == "archive":
        email.is_archived = True
    elif action == "mark_read":
        email.is_read = True
    elif action == "mark_unread":
        email.is_read = False
    elif action == "link_to_candidate":
        # candidate_id presence validated in request model.
        assert candidate_id is not None
        email.candidate_id = candidate_id
        email.match_method = EmailMatchMethod.manual
        email.match_confidence = 1.0
        email.matched_at = now
        email.matched_by_user_id = user_id
    elif action == "unlink":
        email.candidate_id = None
        email.match_method = EmailMatchMethod.unmatched
        email.match_confidence = None
        email.matched_at = None
        email.matched_by_user_id = None
    # `updated_at` mixin column refreshes via TimestampMixin.


@router.post("/microsoft365/emails/bulk", response_model=BulkEmailActionResponse)
@limiter.limit("20/minute")
async def bulk_email_action(
    request: Request,
    payload: BulkEmailActionRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BulkEmailActionResponse:
    """Apply a single action to many emails owned by the current user.

    Multi-tenant scope: `Email.user_id == current_user.id`. Emails belonging to
    other users are reported as `forbidden` skips, never silently mutated.

    Actions:
      - archive          → set is_archived=true
      - mark_read        → set is_read=true
      - mark_unread      → set is_read=false
      - link_to_candidate → set candidate_id (+ match_method=manual)
      - unlink           → clear candidate_id (+ match_method=unmatched)
    """
    requested_ids = sorted(set(payload.email_ids))

    # Validate candidate for link_to_candidate (must exist).
    if payload.action == "link_to_candidate":
        candidate = await db.get(Candidate, payload.candidate_id)
        if candidate is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"candidate {payload.candidate_id} not found",
            )

    rows = await db.execute(select(Email).where(Email.id.in_(requested_ids)))
    emails = list(rows.scalars().all())
    found_by_id = {e.id: e for e in emails}

    errors: list[BulkEmailActionItemError] = []
    updated = 0
    now = datetime.now(timezone.utc)

    for email_id in requested_ids:
        email = found_by_id.get(email_id)
        if email is None:
            errors.append(BulkEmailActionItemError(id=email_id, reason="not_found"))
            continue
        if email.user_id != current_user.id:
            errors.append(BulkEmailActionItemError(id=email_id, reason="forbidden"))
            continue
        _apply_bulk_action(
            email,
            payload.action,
            payload.candidate_id,
            current_user.id,
            now,
        )
        updated += 1

    await db.commit()

    return BulkEmailActionResponse(
        action=payload.action,
        updated_count=updated,
        skipped_count=len(errors),
        errors=errors,
    )
