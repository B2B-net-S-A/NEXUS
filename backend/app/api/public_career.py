"""Publiczne endpointy strony kariery (kariera.dynaminds.pl), bez logowania.

Prefiks ``/api/public/career``:

* ``GET /r/{slug}`` — strona rekrutacji (tylko ZATWIERDZONY opis publiczny);
* ``GET /p/{slug}`` — stały link rekrutera i jego otwarte rekrutacje;
* ``POST /apply`` — formularz (multipart), link po slugu.

Nigdy nie zwracamy nazwy klienta, stawek, budżetu, nazwiska ani kontaktu
rekrutera — odpowiedź budują białe listy z ``services/job_public_profile``.

UWAGA: moduł z ``@limiter.limit`` NIE może mieć ``from __future__ import
annotations`` (PEP 563 + slowapi #579 zamienia parametry formularza w QUERY).
Pilnuje tego ``test_public_surface_hardening.py``.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import EmailStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job
from app.models.job_public_profile import JobPublicProfile
from app.models.user import User
from app.services import job_public_profile as jpp
from app.services.career_slugs import first_name

logger = logging.getLogger(__name__)

router = APIRouter()

_NOT_FOUND = "Nie znaleziono strony."


def _link_active(link: CandidateInviteLink) -> bool:
    if link.revoked:
        return False
    return link.expires_at is None or link.expires_at > datetime.now(timezone.utc)


async def _link_by_slug(
    db: AsyncSession, slug: str, *, kind: Optional[str] = None
) -> Optional[CandidateInviteLink]:
    value = (slug or "").strip().lower()
    if not value or len(value) > 64:
        return None
    query = select(CandidateInviteLink).where(CandidateInviteLink.slug == value)
    if kind is not None:
        query = query.where(CandidateInviteLink.kind == kind)
    return await db.scalar(query)


async def _recruiter_brief(db: AsyncSession, user_id: int) -> dict:
    user = await db.get(User, user_id)
    slug = await db.scalar(
        select(CandidateInviteLink.slug).where(
            CandidateInviteLink.created_by == user_id,
            CandidateInviteLink.kind == "recruiter",
            CandidateInviteLink.revoked.is_(False),
        )
    )
    return {
        "first_name": first_name(user.name if user else None) or "Zespół",
        "slug": slug,
    }


async def _bump_visits(db: AsyncSession, link: CandidateInviteLink) -> None:
    await db.execute(
        update(CandidateInviteLink)
        .where(CandidateInviteLink.token == link.token)
        .values(visit_count=CandidateInviteLink.visit_count + 1)
    )
    await db.commit()


def _no_cache(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Robots-Tag"] = "noindex"


@router.get("/r/{slug}")
@limiter.limit("60/minute")
async def get_career_job(
    request: Request,
    response: Response,
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Strona rekrutacji. 404 dla nieznanego sluga i niezatwierdzonego opisu."""
    link = await _link_by_slug(db, slug, kind="job")
    if link is None or link.job_id is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    profile = await db.get(JobPublicProfile, link.job_id)
    if jpp.profile_status(profile) != jpp.STATUS_APPROVED:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    job = await db.get(Job, link.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=_NOT_FOUND)

    recruiter = await _recruiter_brief(db, link.created_by)
    _no_cache(response)
    if not (_link_active(link) and jpp.job_is_open(job)):
        return {
            "status": "closed",
            "recruiter": recruiter,
            "job": jpp.closed_job_payload(job, link.slug),
        }

    payload = jpp.public_job_payload(
        job,
        link_slug=link.slug,
        subtitle=profile.subtitle,
        about=profile.about,
        sections=profile.sections,
    )
    await _bump_visits(db, link)
    return {"status": "open", "recruiter": recruiter, "job": payload}


@router.get("/p/{slug}")
@limiter.limit("60/minute")
async def get_career_recruiter(
    request: Request,
    response: Response,
    slug: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Stały link rekrutera i jego otwarte, zatwierdzone rekrutacje."""
    link = await _link_by_slug(db, slug, kind="recruiter")
    if link is None or not _link_active(link):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    owner_id = link.created_by

    rows = (
        await db.execute(
            select(CandidateInviteLink, Job, JobPublicProfile)
            .join(Job, Job.id == CandidateInviteLink.job_id)
            .join(JobPublicProfile, JobPublicProfile.job_id == Job.id)
            .where(
                CandidateInviteLink.created_by == owner_id,
                CandidateInviteLink.kind == "job",
                CandidateInviteLink.revoked.is_(False),
                CandidateInviteLink.slug.is_not(None),
                JobPublicProfile.show_on_recruiter_page.is_(True),
            )
            .order_by(CandidateInviteLink.created_at.desc())
        )
    ).all()
    jobs: list[dict] = []
    seen: set[int] = set()
    for job_link, job, profile in rows:
        if job.id in seen or not _link_active(job_link) or not jpp.job_is_open(job):
            continue
        if jpp.profile_status(profile) != jpp.STATUS_APPROVED:
            continue
        seen.add(job.id)
        params = jpp.public_params(job)
        jobs.append(
            {
                "slug": job_link.slug,
                "title": job.title,
                "city": params["city"],
                "remote_policy": params["remote_policy"],
            }
        )

    recruiter = await _recruiter_brief(db, owner_id)
    await _bump_visits(db, link)
    _no_cache(response)
    return {"recruiter": recruiter, "jobs": jobs}


async def _apply_link(db: AsyncSession, slug: str) -> CandidateInviteLink:
    """Link, przez który wolno dziś aplikować — inaczej 404."""
    link = await _link_by_slug(db, slug)
    if link is None or not _link_active(link):
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    if link.kind == "job":
        job = await db.get(Job, link.job_id) if link.job_id else None
        if not jpp.job_is_open(job):
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        profile = await db.get(JobPublicProfile, link.job_id)
        if jpp.profile_status(profile) != jpp.STATUS_APPROVED:
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return link


@router.post("/apply", status_code=status.HTTP_201_CREATED, response_model=None)
@limiter.limit("5/minute; 30/hour")
async def submit_career_apply(
    request: Request,
    background_tasks: BackgroundTasks,
    link_slug: str = Form(..., min_length=1, max_length=64),
    first_name: str = Form(..., min_length=1, max_length=100),
    last_name: str = Form(..., min_length=1, max_length=100),
    email: EmailStr = Form(...),
    cv: UploadFile = File(...),
    consent: Optional[str] = Form(None, max_length=10),
    expected_rate_hourly: Optional[str] = Form(None, max_length=20),
    availability_date: Optional[str] = Form(None, max_length=20),
    city: Optional[str] = Form(None, max_length=200),
    work_mode: Optional[str] = Form(None, max_length=20),
    website: Optional[str] = Form(None, max_length=500),
    utm_source: Optional[str] = Form(None, max_length=120),
    utm_medium: Optional[str] = Form(None, max_length=120),
    utm_campaign: Optional[str] = Form(None, max_length=120),
    utm_term: Optional[str] = Form(None, max_length=120),
    utm_content: Optional[str] = Form(None, max_length=120),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Zgłoszenie ze strony kariery (link rekrutacji albo stały link)."""
    from app.api.public_share import _validate_cv_file
    from app.services import public_apply

    # Pułapka na boty: ukryte pole wypełnione = cichy sukces, zero zapisu.
    if website and website.strip():
        return {"ok": True, "status": "received"}

    link = await _apply_link(db, link_slug)
    public_apply.require_consent(consent)
    optional = public_apply.parse_optional_fields(
        expected_rate_hourly=expected_rate_hourly,
        availability_date=availability_date,
        city=city,
        work_mode=work_mode,
    )
    content = await cv.read()
    _validate_cv_file(cv, content)

    applicant = public_apply.ApplicantInput(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        email=str(email),
        utm={
            "source": utm_source,
            "medium": utm_medium,
            "campaign": utm_campaign,
            "term": utm_term,
            "content": utm_content,
        },
        **optional,
    )
    return await public_apply.submit_application(
        db,
        ref=public_apply.LinkRef(
            link=link,
            digest=public_apply.link_key(link),
            audit_prefix=(link.slug or "")[:8] or "career",
            via="career",
        ),
        applicant=applicant,
        cv=cv,
        content=content,
        background_tasks=background_tasks,
    )
