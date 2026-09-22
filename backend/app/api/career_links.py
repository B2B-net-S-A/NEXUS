"""Strona kariery — endpointy NEXUSA (zalogowani rekruterzy).

* ``/api/me/career-link`` — stały link rekrutera (``kind='recruiter'``):
  odczyt ze statystykami, ustawienie/zmiana sluga, odwołanie, sprawdzenie
  dostępności sluga;
* ``/api/jobs/{job_id}/public-profile`` — publiczny opis rekrutacji:
  odczyt z podglądem i znaleziskami kontroli, zapis szkicu, szkic AI,
  zatwierdzenie (odmawia 422 przy znaleziskach), widoczność na stronie
  rekrutera.

Bramka jak przy linkach aplikacyjnych: rola ``RecruiterPlus`` + sekcja
Pipeline (router), a endpointy rekrutacji dodatkowo członkostwo w niej.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.application_submission import ApplicationSubmission
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job
from app.models.job_public_profile import JobPublicProfile
from app.models.user import User
from app.schemas.invite_link import (
    CareerLinkBrief,
    CareerLinkJob,
    CareerLinkResponse,
    CareerLinkStats,
    CareerLinkUpdate,
    PublicProfileDraft,
    PublicProfileResponse,
    PublicProfileUpdate,
    PublicProfileVisibility,
    PublicSections,
    SlugAvailability,
)
from app.services import job_public_profile as jpp
from app.services.career_slugs import (
    career_base_url,
    recruiter_base_url,
    recruiter_link_url,
    recruiter_slug_problem,
    suggest_recruiter_slug,
)
from app.services.public_apply import link_key

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

_STATS_DAYS = 30
_SLUG_TAKEN = "Ten adres jest już zajęty."


# ── Stały link rekrutera ────────────────────────────────────────────────────


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _active(link: CandidateInviteLink) -> bool:
    return not link.revoked and (link.expires_at is None or link.expires_at > _now())


async def _own_recruiter_link(
    db: AsyncSession, user_id: int
) -> Optional[CandidateInviteLink]:
    return await db.scalar(
        select(CandidateInviteLink).where(
            CandidateInviteLink.created_by == user_id,
            CandidateInviteLink.kind == "recruiter",
            CandidateInviteLink.revoked.is_(False),
        )
    )


async def _slug_owner(db: AsyncSession, slug: str) -> Optional[CandidateInviteLink]:
    return await db.scalar(
        select(CandidateInviteLink).where(CandidateInviteLink.slug == slug)
    )


async def _stats(
    db: AsyncSession, link: Optional[CandidateInviteLink]
) -> CareerLinkStats:
    if link is None:
        return CareerLinkStats(days=_STATS_DAYS)
    since = _now() - timedelta(days=_STATS_DAYS)
    key = link_key(link)
    new_candidates = int(
        await db.scalar(
            select(func.count(Activity.id)).where(
                Activity.entity_type == "candidate",
                Activity.action == "applied_via_invite",
                Activity.created_at >= since,
                Activity.details["invite_token_sha256"].astext == key,
            )
        )
        or 0
    )
    duplicates = int(
        await db.scalar(
            select(func.count(ApplicationSubmission.id)).where(
                ApplicationSubmission.invite_link_token_sha256 == key,
                ApplicationSubmission.created_at >= since,
            )
        )
        or 0
    )
    return CareerLinkStats(
        days=_STATS_DAYS,
        applications=new_candidates + duplicates,
        new_candidates=new_candidates,
    )


async def _career_jobs(db: AsyncSession, user_id: int) -> list[CareerLinkJob]:
    rows = (
        await db.execute(
            select(CandidateInviteLink, Job, JobPublicProfile)
            .join(Job, Job.id == CandidateInviteLink.job_id)
            .outerjoin(JobPublicProfile, JobPublicProfile.job_id == Job.id)
            .where(
                CandidateInviteLink.created_by == user_id,
                CandidateInviteLink.kind == "job",
                CandidateInviteLink.revoked.is_(False),
            )
            .order_by(CandidateInviteLink.created_at.desc())
        )
    ).all()
    out: list[CareerLinkJob] = []
    seen: set[int] = set()
    names_cache: dict[Optional[int], list[str]] = {}
    for link, job, profile in rows:
        if job.id in seen or not _active(link) or not jpp.job_is_open(job):
            continue
        seen.add(job.id)
        status_value, _default, title = await jpp.resolve_status(
            db, job, profile, names_cache=names_cache
        )
        out.append(
            CareerLinkJob(
                job_id=job.id,
                title=title,
                profile_status=status_value,
                show_on_recruiter_page=(
                    profile.show_on_recruiter_page if profile is not None else True
                ),
                has_link=True,
            )
        )
    return out


async def _career_link_response(db: AsyncSession, user: User) -> CareerLinkResponse:
    link = await _own_recruiter_link(db, user.id)
    brief = (
        CareerLinkBrief(
            slug=link.slug,
            public_url=recruiter_link_url(link.slug),
            created_at=link.created_at,
            visit_count=link.visit_count or 0,
        )
        if link is not None and link.slug
        else None
    )
    return CareerLinkResponse(
        link=brief,
        base_url=career_base_url(),
        recruiter_base_url=recruiter_base_url(),
        stats=await _stats(db, link),
        suggested_slug=link.slug
        if link is not None and link.slug
        else (suggest_recruiter_slug(user.name)),
        jobs=await _career_jobs(db, user.id),
    )


@router.get("/me/career-link", response_model=CareerLinkResponse)
async def get_my_career_link(
    current_user: RecruiterPlus, db: AsyncSession = Depends(get_db)
) -> CareerLinkResponse:
    return await _career_link_response(db, current_user)


@router.get("/me/career-link/slug-available", response_model=SlugAvailability)
async def check_career_slug(
    current_user: RecruiterPlus,
    slug: str = Query(..., max_length=64),
    db: AsyncSession = Depends(get_db),
) -> SlugAvailability:
    value = slug.strip().lower()
    problem = recruiter_slug_problem(value)
    if problem:
        return SlugAvailability(available=False, reason=problem)
    owner = await _slug_owner(db, value)
    if owner is not None:
        own = await _own_recruiter_link(db, current_user.id)
        mine = owner.kind == "recruiter" and owner.created_by == current_user.id
        if not mine or (owner.revoked and own is not None):
            return SlugAvailability(available=False, reason=_SLUG_TAKEN)
    return SlugAvailability(available=True)


def _new_recruiter_link(user_id: int, slug: str) -> CandidateInviteLink:
    """Stały link: sekret istnieje tylko jako skrót (PK = klucz odwołania).

    Stały link nie ma adresu z tokenem — kandydat wchodzi po slugu — więc
    surowy sekret nie jest nigdzie potrzebny i nie jest przechowywany.
    """
    secret = secrets.token_urlsafe(36)
    return CandidateInviteLink(
        token=f"v2${secrets.token_hex(16)}",
        token_sha256=hashlib.sha256(secret.encode()).hexdigest(),
        created_by=user_id,
        kind="recruiter",
        slug=slug,
        job_id=None,
        expires_at=None,
    )


@router.put("/me/career-link", response_model=CareerLinkResponse)
async def put_my_career_link(
    data: CareerLinkUpdate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> CareerLinkResponse:
    slug = data.slug.strip().lower()
    problem = recruiter_slug_problem(slug)
    if problem:
        raise HTTPException(status_code=422, detail=problem)
    own = await _own_recruiter_link(db, current_user.id)
    owner = await _slug_owner(db, slug)
    reclaim = (
        own is None
        and owner is not None
        and owner.kind == "recruiter"
        and owner.created_by == current_user.id
    )
    if owner is not None and not reclaim and (own is None or owner.token != own.token):
        raise HTTPException(status_code=409, detail=_SLUG_TAKEN)
    if reclaim:
        # Własny, wcześniej odwołany link z tym adresem — wraca do życia
        # (slug jest unikalny także wśród odwołanych).
        owner.revoked = False
    elif own is None:
        db.add(_new_recruiter_link(current_user.id, slug))
    elif own.slug != slug:
        own.slug = slug
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=_SLUG_TAKEN) from None
    return await _career_link_response(db, current_user)


@router.delete("/me/career-link", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_career_link(
    current_user: RecruiterPlus, db: AsyncSession = Depends(get_db)
) -> Response:
    own = await _own_recruiter_link(db, current_user.id)
    if own is not None:
        own.revoked = True
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Publiczny opis rekrutacji ───────────────────────────────────────────────


async def _load_job(db: AsyncSession, user: User, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji")
    await ensure_job_membership(db, user, job_id)
    return job


async def _preview_slug(db: AsyncSession, user: User, job_id: int) -> Optional[str]:
    rows = (
        await db.execute(
            select(CandidateInviteLink)
            .where(
                CandidateInviteLink.job_id == job_id,
                CandidateInviteLink.kind == "job",
                CandidateInviteLink.revoked.is_(False),
                CandidateInviteLink.slug.is_not(None),
            )
            .order_by(
                (CandidateInviteLink.created_by == user.id).desc(),
                CandidateInviteLink.created_at.desc(),
            )
        )
    ).scalars()
    for link in rows:
        if _active(link):
            return link.slug
    return None


async def _profile_response(
    db: AsyncSession, user: User, job: Job, profile: Optional[JobPublicProfile]
) -> PublicProfileResponse:
    subtitle = profile.subtitle if profile else None
    about = profile.about if profile else None
    sections = jpp.normalize_sections(profile.sections if profile else None)
    status_value, default_title, effective_title = await jpp.resolve_status(
        db, job, profile
    )
    preview = jpp.public_job_payload(
        job,
        title=effective_title,
        link_slug=await _preview_slug(db, user, job.id),
        subtitle=subtitle,
        about=about,
        sections=sections,
    )
    findings = await jpp.lint_payload(db, job, preview)
    approved_by_name: Optional[str] = None
    if profile is not None and profile.approved_by:
        approved_by_name = await db.scalar(
            select(User.name).where(User.id == profile.approved_by)
        )
    return PublicProfileResponse(
        job_id=job.id,
        status=status_value,
        public_title=profile.public_title if profile else None,
        default_title=default_title,
        effective_title=effective_title,
        subtitle=subtitle,
        about=about,
        sections=PublicSections(**sections),
        show_on_recruiter_page=(
            profile.show_on_recruiter_page if profile is not None else True
        ),
        approved_at=profile.approved_at if profile else None,
        approved_by_name=approved_by_name,
        findings=[f.as_dict() for f in findings],
        preview=preview,
    )


@router.get("/jobs/{job_id}/public-profile", response_model=PublicProfileResponse)
async def get_public_profile(
    job_id: int, current_user: RecruiterPlus, db: AsyncSession = Depends(get_db)
) -> PublicProfileResponse:
    job = await _load_job(db, current_user, job_id)
    profile = await db.get(JobPublicProfile, job_id)
    return await _profile_response(db, current_user, job, profile)


@router.put("/jobs/{job_id}/public-profile", response_model=PublicProfileResponse)
async def put_public_profile(
    job_id: int,
    data: PublicProfileUpdate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> PublicProfileResponse:
    """Zapis szkicu. Zmiana treści po zatwierdzeniu = status ``draft``.

    Nie trzeba niczego odznaczać: status wynika ze skrótu treści, a skrót
    zatwierdzonej wersji przestaje pasować przy pierwszej zmianie.
    """
    job = await _load_job(db, current_user, job_id)
    profile = await db.get(JobPublicProfile, job_id)
    if profile is None:
        profile = JobPublicProfile(job_id=job_id)
        db.add(profile)
    fields = data.model_fields_set
    if "public_title" in fields:
        title = " ".join((data.public_title or "").split())
        profile.public_title = title[: jpp.PUBLIC_TITLE_MAX] or None
    if "subtitle" in fields:
        profile.subtitle = (data.subtitle or "").strip() or None
    if "about" in fields:
        profile.about = (data.about or "").strip() or None
    if "sections" in fields and data.sections is not None:
        profile.sections = data.sections.model_dump()
    elif profile.sections is None:
        profile.sections = jpp.normalize_sections(None)
    if "show_on_recruiter_page" in fields and data.show_on_recruiter_page is not None:
        profile.show_on_recruiter_page = data.show_on_recruiter_page
    profile.updated_by = current_user.id
    await db.commit()
    await db.refresh(profile)
    return await _profile_response(db, current_user, job, profile)


@router.put(
    "/jobs/{job_id}/public-profile/visibility",
    response_model=PublicProfileResponse,
)
async def put_public_profile_visibility(
    job_id: int,
    data: PublicProfileVisibility,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> PublicProfileResponse:
    """Widoczność na stronie rekrutera — bez zmiany statusu zatwierdzenia."""
    job = await _load_job(db, current_user, job_id)
    profile = await db.get(JobPublicProfile, job_id)
    if profile is None:
        profile = JobPublicProfile(job_id=job_id, sections=jpp.normalize_sections(None))
        db.add(profile)
    profile.show_on_recruiter_page = data.show_on_recruiter_page
    profile.updated_by = current_user.id
    await db.commit()
    await db.refresh(profile)
    return await _profile_response(db, current_user, job, profile)


@router.post("/jobs/{job_id}/public-profile/draft", response_model=PublicProfileDraft)
async def draft_public_profile(
    job_id: int, current_user: RecruiterPlus, db: AsyncSession = Depends(get_db)
) -> PublicProfileDraft:
    """Szkic AI — NIE zapisywany; rekruter wkleja go do edytora i zatwierdza."""
    job = await _load_job(db, current_user, job_id)
    try:
        draft = await jpp.generate_draft(db, job, user_id=current_user.id)
    except jpp.PublicDraftUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Szkic AI jest chwilowo niedostępny. Spróbuj ponownie za chwilę "
                "albo napisz opis ręcznie."
            ),
        ) from exc
    return PublicProfileDraft(**draft)


@router.post(
    "/jobs/{job_id}/public-profile/approve", response_model=PublicProfileResponse
)
async def approve_public_profile(
    job_id: int, current_user: RecruiterPlus, db: AsyncSession = Depends(get_db)
) -> PublicProfileResponse:
    """Zatwierdzenie = publikacja. Odmawia 422 przy KAŻDYM znalezisku kontroli."""
    job = await _load_job(db, current_user, job_id)
    profile = await db.get(JobPublicProfile, job_id)
    if profile is None or not (
        (profile.subtitle or "").strip() or (profile.about or "").strip()
    ):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PUBLIC_PROFILE_EMPTY",
                "message": "Najpierw napisz i zapisz opis rekrutacji.",
                "findings": [],
            },
        )
    _default_title, effective_title = await jpp.public_titles(db, job, profile)
    preview = jpp.public_job_payload(
        job,
        title=effective_title,
        link_slug=None,
        subtitle=profile.subtitle,
        about=profile.about,
        sections=profile.sections,
    )
    findings = await jpp.lint_payload(db, job, preview)
    if findings:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PUBLIC_PROFILE_FINDINGS",
                "message": (
                    "Opis zawiera treści, których nie publikujemy — popraw je "
                    "przed zatwierdzeniem."
                ),
                "findings": [f.as_dict() for f in findings],
            },
        )
    profile.approved_at = _now()
    profile.approved_by = current_user.id
    profile.approved_hash = jpp.content_hash(
        profile.subtitle, profile.about, profile.sections, effective_title
    )
    profile.updated_by = current_user.id
    await db.commit()
    await db.refresh(profile)
    return await _profile_response(db, current_user, job, profile)
