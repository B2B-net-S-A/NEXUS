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
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job
from app.models.job_public_profile import JobPublicProfile
from app.models.recruitment_priority import PriorityChannel, PriorityMemberStatus
from app.models.user import User, UserRole
from app.schemas.invite_link import (
    InviteLinkCreate,
    InviteLinkCreatorBrief,
    InviteLinkJobBrief,
    InviteLinkResponse,
    InviteLinkStatus,
)
from app.services.priority_work_policy import (
    assert_priority_work_access,
    current_priority_assignment,
)
from app.services.career_slugs import job_link_url
from app.services.job_public_profile import job_is_open, public_titles, safe_job_slug
from app.services.priority_work_service import audit_event

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


def _resolve_status(
    link: CandidateInviteLink, job: Optional[Job] = None
) -> InviteLinkStatus:
    """Derive UI status from link state. Priority: revoked > expired > used > active.

    0339: link bez terminu (``expires_at IS NULL``) wygasa razem z rekrutacją —
    zamknięta rekrutacja = ``expired``.
    """
    if link.revoked:
        return "revoked"
    if link.expires_at is not None and link.expires_at < datetime.now(timezone.utc):
        return "expired"
    if job is not None and link.kind == "job" and not job_is_open(job):
        return "expired"
    if link.use_count > 0:
        return "used"
    return "active"


def _build_url(token: str) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/apply/{token}"


def _invite_raw_token(link: CandidateInviteLink) -> Optional[str]:
    """The secret that goes into the /apply URL.

    v2 rows keep it only as Fernet ciphertext (token_ct); legacy rows kept the
    raw value in the PK. Returns None if a v2 ciphertext cannot be decrypted
    (e.g. the key was rotated) so the list renders without crashing — the link
    is simply no longer reconstructible and the recruiter must reissue it.
    """
    if link.token_ct:
        from app.core.encryption import TokenCipherNotConfigured, get_token_cipher

        try:
            return get_token_cipher().decrypt(link.token_ct)
        except TokenCipherNotConfigured:
            return None
    return link.token  # legacy plaintext PK


def _to_response(
    link: CandidateInviteLink,
    job: Job,
    creator: Optional[User],
) -> InviteLinkResponse:
    raw = _invite_raw_token(link)
    # Link ze slugiem prowadzi na stronę kariery; stary link bez sluga — na
    # dotychczasowy formularz `/apply/{token}`.
    if link.slug:
        public_url = job_link_url(link.slug)
    else:
        public_url = _build_url(raw) if raw else ""
    return InviteLinkResponse(
        token=raw or "",
        url=public_url,
        public_url=public_url,
        kind=link.kind or "job",
        slug=link.slug,
        visit_count=link.visit_count or 0,
        job=InviteLinkJobBrief(id=job.id, title=job.title),
        label=link.label,
        expires_at=link.expires_at,
        revoked=link.revoked,
        use_count=link.use_count,
        last_used_at=link.last_used_at,
        created_at=link.created_at,
        status=_resolve_status(link, job),
        origin_assignment_id=link.origin_assignment_id,
        priority_compliant_at_create=link.priority_compliant_at_create,
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
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji")
    # Link żyje do zamknięcia rekrutacji — wystarczy, że jest opublikowana
    # (flaga ``is_open`` „przekazana do searchu" miała 14 z 306 rekrutacji).
    if not job_is_open(job):
        raise HTTPException(
            status_code=400,
            detail="Link aplikacyjny można utworzyć tylko dla opublikowanej rekrutacji.",
        )

    decision = await assert_priority_work_access(
        db,
        candidate_id=0,
        job_id=job.id,
        actor_user_id=current_user.id,
        action="create_invite_link",
        continuation_exists=False,
        consume_exception=False,
        work_channel=PriorityChannel.linkedin,
        job_is_open=True,
    )
    origin_assignment_id = decision.assignment_id
    priority_compliant = decision.priority_compliant
    if origin_assignment_id is None:
        assignment, member, _plan = await current_priority_assignment(
            db,
            user_id=current_user.id,
            job_id=job.id,
        )
        if (
            assignment is not None
            and member is not None
            and member.status == PriorityMemberStatus.active
        ):
            origin_assignment_id = assignment.id
            priority_compliant = True

    import hashlib

    from app.core.encryption import TokenCipherNotConfigured, get_token_cipher

    raw_token = secrets.token_urlsafe(36)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=data.expires_in_days)
        if data.expires_in_days
        else None
    )
    # Slug z tytułu publicznego — surowy tytuł niesie nazwę klienta i kody.
    profile = await db.get(JobPublicProfile, job.id)
    _default_title, public_title = await public_titles(db, job, profile)
    slug = await safe_job_slug(db, job, public_title)
    # v2 when an encryption key is configured: PK = non-secret revoke key, the
    # secret lives only as a SHA-256 (for lookup) and Fernet ciphertext (so the
    # list can rebuild the URL). Fall back to the legacy plaintext PK if no key
    # is set, so invite creation never breaks on a missing secret.
    try:
        ciphertext = get_token_cipher().encrypt(raw_token)
        link = CandidateInviteLink(
            token=f"v2${secrets.token_hex(16)}",
            token_sha256=hashlib.sha256(raw_token.encode()).hexdigest(),
            token_ct=ciphertext,
            created_by=current_user.id,
            kind="job",
            slug=slug,
            job_id=job.id,
            origin_assignment_id=origin_assignment_id,
            priority_compliant_at_create=priority_compliant,
            label=data.label,
            expires_at=expires_at,
        )
    except TokenCipherNotConfigured:
        link = CandidateInviteLink(
            token=raw_token,
            created_by=current_user.id,
            kind="job",
            slug=slug,
            job_id=job.id,
            origin_assignment_id=origin_assignment_id,
            priority_compliant_at_create=priority_compliant,
            label=data.label,
            expires_at=expires_at,
        )
    db.add(link)
    await db.flush()
    audit_event(
        db,
        "invite_link_created",
        actor_user_id=current_user.id,
        job_id=job.id,
        assignment_id=origin_assignment_id,
        payload={
            "expires_at": expires_at.isoformat() if expires_at else None,
            "slug": slug,
            "priority_mode": decision.mode.value,
            "priority_compliant": priority_compliant,
        },
    )
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
    is_privileged = current_user.has_any_role(UserRole.admin, UserRole.delivery_lead)
    query = (
        select(CandidateInviteLink)
        .options(
            selectinload(CandidateInviteLink.job),
            selectinload(CandidateInviteLink.creator),
        )
        .where(CandidateInviteLink.kind == "job")
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
    import hashlib

    digest = hashlib.sha256(token.encode()).hexdigest()
    row = await db.scalar(
        select(CandidateInviteLink).where(
            (CandidateInviteLink.token_sha256 == digest)
            | (
                (CandidateInviteLink.token == token)
                & (CandidateInviteLink.token_sha256.is_(None))
            )
        )
    )
    if row is None:
        raise HTTPException(
            status_code=404, detail="Nie znaleziono linku aplikacyjnego"
        )
    is_owner = row.created_by == current_user.id
    is_privileged = current_user.has_any_role(UserRole.admin, UserRole.delivery_lead)
    if not (is_owner or is_privileged):
        raise HTTPException(
            status_code=403,
            detail="Nie możesz unieważnić tego linku — może to zrobić jego autor, Delivery Lead albo administrator",
        )
    row.revoked = True
    await db.commit()
    return None
