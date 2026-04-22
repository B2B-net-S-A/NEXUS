"""Recruiter-facing invite link endpoints.

A recruiter (RecruiterPlus) creates a multi-use, job-scoped, time-limited
link. Candidates apply through /apply/{token} (public, see public_share.py).
Every successful application sets `candidates.created_by = link.created_by`,
attributing ownership to whoever posted the link.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, RecruiterPlus
from app.core.config import settings
from app.core.database import get_db
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.schemas.invite_link import (
    InviteLinkCreate,
    InviteLinkCreatorBrief,
    InviteLinkJobBrief,
    InviteLinkResponse,
    InviteLinkStatus,
)

router = APIRouter()


def _resolve_status(link: CandidateInviteLink) -> InviteLinkStatus:
    """Derive UI status from link state. Priority: revoked > expired > used > active."""
    if link.revoked:
        return "revoked"
    if link.expires_at < datetime.now(timezone.utc):
        return "expired"
    if link.use_count > 0:
        return "used"
    return "active"


def _build_url(token: str) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/apply/{token}"


def _to_response(
    link: CandidateInviteLink,
    job: Job,
    creator: Optional[User],
) -> InviteLinkResponse:
    return InviteLinkResponse(
        token=link.token,
        url=_build_url(link.token),
        job=InviteLinkJobBrief(id=job.id, title=job.title),
        label=link.label,
        expires_at=link.expires_at,
        revoked=link.revoked,
        use_count=link.use_count,
        last_used_at=link.last_used_at,
        created_at=link.created_at,
        status=_resolve_status(link),
        created_by_user=(
            InviteLinkCreatorBrief(id=creator.id, name=creator.name)
            if creator
            else None
        ),
    )


@router.post("", response_model=InviteLinkResponse, status_code=status.HTTP_201_CREATED)
async def create_invite_link(
    data: InviteLinkCreate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    """Generate a new invite link for a published job.

    Only published jobs are accepted — preventing recruiters from sharing
    links to drafts or closed positions.
    """
    job = await db.scalar(select(Job).where(Job.id == data.job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != JobStatus.published:
        raise HTTPException(
            status_code=400,
            detail="Job must be published to generate an invite link",
        )

    token = secrets.token_urlsafe(36)
    expires_at = datetime.now(timezone.utc) + timedelta(days=data.expires_in_days)
    link = CandidateInviteLink(
        token=token,
        created_by=current_user.id,
        job_id=job.id,
        label=data.label,
        expires_at=expires_at,
    )
    db.add(link)
    await db.commit()
    await db.refresh(link)

    return _to_response(link, job, current_user)


@router.get("", response_model=list[InviteLinkResponse])
async def list_invite_links(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    mine: bool = Query(True, description="List only caller's links."),
    status_filter: Optional[
        Literal["active", "used", "revoked", "expired", "all"]
    ] = Query("all", alias="status"),
):
    """List invite links. Non-admin/non-lead callers can only view their own.

    Admins and delivery_leads may pass `mine=false` to view all links in the org.
    """
    is_privileged = current_user.role in (UserRole.admin, UserRole.delivery_lead)
    query = (
        select(CandidateInviteLink)
        .options(
            selectinload(CandidateInviteLink.job),
            selectinload(CandidateInviteLink.creator),
        )
        .order_by(CandidateInviteLink.created_at.desc())
    )
    if mine or not is_privileged:
        query = query.where(CandidateInviteLink.created_by == current_user.id)

    rows = list((await db.execute(query)).scalars().all())

    response: list[InviteLinkResponse] = []
    for row in rows:
        item = _to_response(row, row.job, row.creator)
        if status_filter and status_filter != "all" and item.status != status_filter:
            continue
        response.append(item)
    return response


@router.post("/{token}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite_link(
    token: str,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete an invite link. Owner or admin/delivery_lead only."""
    row = await db.scalar(
        select(CandidateInviteLink).where(CandidateInviteLink.token == token)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Link not found")
    is_owner = row.created_by == current_user.id
    is_privileged = current_user.role in (UserRole.admin, UserRole.delivery_lead)
    if not (is_owner or is_privileged):
        raise HTTPException(status_code=403, detail="Not allowed to revoke this link")
    row.revoked = True
    await db.commit()
    return None
