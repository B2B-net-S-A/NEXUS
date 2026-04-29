"""Email thread endpoints used by the candidate-detail UI.

GET  /api/candidates/{id}/emails          → list conversations (grouped)
GET  /api/emails/{id}                     → full email w/ attachments
GET  /api/emails/{id}/attachments/{aid}/download → binary
POST /api/candidates/{id}/emails/compose  → new email in candidate context
POST /api/candidates/{id}/emails/reply    → reply to an existing email
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
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
    is_private_filtered: bool
    match_method: str
    match_confidence: Optional[float]
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
        is_private_filtered=email.is_private_filtered,
        match_method=email.match_method.value if email.match_method else "unmatched",
        match_confidence=email.match_confidence,
        attachments=[],  # filled by callers that eager-load
    )


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/candidates/{candidate_id}/emails", response_model=list[ThreadPreview])
async def list_candidate_emails(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> list[ThreadPreview]:
    """Return conversation previews for a candidate, most-recent first.

    Groups by `m365_conversation_id`. Each preview carries the latest message
    plus aggregate counts (total + unread).
    """
    # Fetch all candidate emails the user can see, latest first.
    base_stmt = (
        select(Email)
        .where(Email.candidate_id == candidate_id)
        .order_by(Email.received_at.desc())
        .limit(1000)  # cap for safety — UI paginates by thread count
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
