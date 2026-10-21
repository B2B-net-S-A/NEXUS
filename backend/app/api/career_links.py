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

from app.api.deps import OperationalUser, RecruiterPlus
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.application_submission import ApplicationSubmission
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job, JobStatus
from app.models.job_public_profile import JobPublicProfile
from app.models.user import User
from app.services import career_theme as ct
from app.schemas.invite_link import (
    CareerLinkBrief,
    CareerLinkJob,
    CareerLinkResponse,
    CareerLinkResultCounts,
    CareerLinkResultRow,
    CareerLinkResults,
    CareerLinkStats,
    CareerLinkUpdate,
    PublicProfileDraft,
    PublicProfileLive,
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
from app.services.job_ad.text import visible
from app.services.public_profile_lint import lint_internal_codes, lint_public_texts
from app.services.public_apply import link_key

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

_STATS_DAYS = 30
_SLUG_TAKEN = "Ten adres jest już zajęty."
# „O mnie” na stronie rekrutera: dwa zdania (makieta 6d, 20.10.2026).
ABOUT_MAX = 280


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
                # Od 22.09.2026 zgłoszenie osoby już w bazie też zostawia
                # `applied_via_invite` (z `was_duplicate`) — liczy się niżej.
                func.coalesce(Activity.details["was_duplicate"].astext, "false")
                != "true",
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
            about=link.about or None,
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


@router.get("/me/career-link/results", response_model=CareerLinkResults)
async def get_my_link_results(
    current_user: RecruiterPlus,
    days: int = Query(30, ge=0, le=3650),
    db: AsyncSession = Depends(get_db),
) -> CareerLinkResults:
    """Lejek każdego linku osoby (etap 4 linków, 19.10.2026). ``days=0`` = od początku.

    Wycofane, wygasłe i zamknięte linki bez zgłoszeń w oknie nie są pokazywane.
    """
    from app.services import career_link_results as clr
    from app.services.career_slugs import job_link_url

    since = None if days == 0 else _now() - timedelta(days=days)
    results = await clr.link_results(db, current_user.id, since)
    job_ids = {r.job_id for r in results if r.job_id is not None}
    jobs = (
        {
            j.id: j
            for j in (
                await db.execute(select(Job).where(Job.id.in_(job_ids)))
            ).scalars()
        }
        if job_ids
        else {}
    )
    names_cache: dict[Optional[int], list[str]] = {}
    rows: list[CareerLinkResultRow] = []
    for item in results:
        job = jobs.get(item.job_id) if item.job_id is not None else None
        if item.revoked:
            state = "revoked"
        elif item.expires_at is not None and item.expires_at < _now():
            state = "expired"
        elif item.kind == "job" and not jpp.job_is_open(job):
            state = "closed"
        elif item.kind == "job":
            profile = await db.get(JobPublicProfile, item.job_id)
            version = await jpp.published_version(
                db, job, profile, names_cache=names_cache
            )
            state = "live" if version is not None else "not_live"
        else:
            state = "live"
        if state in ("revoked", "expired", "closed") and item.applications == 0:
            continue
        if not item.slug:
            public_url = None
        elif item.kind == "job":
            public_url = job_link_url(item.slug)
        else:
            public_url = recruiter_link_url(item.slug)
        rows.append(
            CareerLinkResultRow(
                **clr.as_dict(item),
                public_url=public_url,
                job_title=(job.working_title or job.title) if job else None,
                state=state,
            )
        )
    rows.sort(key=lambda r: (r.kind != "job", -r.applications, r.job_title or ""))
    # Suma widocznych wierszy — kafel liczony z innego zbioru niż lista pod
    # nim nie daje się sprawdzić wzrokiem.
    totals = {
        key: sum(getattr(r, key) for r in rows)
        for key in CareerLinkResultCounts.model_fields
    }
    return CareerLinkResults(
        days=days or None, totals=CareerLinkResultCounts(**totals), links=rows
    )


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


async def _about_findings(db: AsyncSession, user: User, about: str) -> list[dict]:
    """Kontrola „O mnie” — ta sama co opisu rekrutacji (etap 6, 20.10.2026).

    Klienci: wszystkich otwartych rekrutacji, które osoba prowadzi albo do
    których ma aktywny link (zdanie „rekrutuję dla …” pisze się o nich).
    Osoby: sama rekruterka — na stronie kariery jest tylko imię, więc nazwisko
    w „O mnie” to znalezisko. Kody zgłoszeń klientów jak w opisie rekrutacji.
    """
    linked = select(CandidateInviteLink.job_id).where(
        CandidateInviteLink.created_by == user.id,
        CandidateInviteLink.kind == "job",
        CandidateInviteLink.revoked.is_(False),
        CandidateInviteLink.job_id.is_not(None),
    )
    client_ids = (
        await db.execute(
            select(Job.client_id)
            .where(
                Job.status == JobStatus.published,
                Job.client_id.is_not(None),
                (Job.recruiter_id == user.id) | Job.id.in_(linked),
            )
            .distinct()
        )
    ).scalars()
    client_names: list[str] = []
    for client_id in client_ids:
        client_names.extend(await jpp.client_lint_names(db, client_id))
    findings = [
        *lint_public_texts(
            [about], client_names=client_names, person_names=[user.name]
        ),
        *lint_internal_codes([about]),
    ]
    return [f.as_dict() for f in findings]


async def _clean_about(
    db: AsyncSession, user: User, raw: Optional[str]
) -> Optional[str]:
    """„O mnie” do zapisu albo 422. Pusty tekst = usuń."""
    # Znaki formatujące (Cf) wycinamy jak w opisie rekrutacji
    # (``put_public_profile``); nowe linie zlewamy — to dwa zdania pod imieniem.
    about = " ".join(visible(raw or "").split())
    if not about:
        return None
    if len(about) > ABOUT_MAX:
        raise HTTPException(
            status_code=422,
            detail=f"„O mnie” może mieć najwyżej {ABOUT_MAX} znaków (dwa zdania).",
        )
    findings = await _about_findings(db, user, about)
    if findings:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "CAREER_ABOUT_FINDINGS",
                "message": (
                    "„O mnie” zawiera treści, których nie publikujemy na stronie "
                    "kariery — popraw je przed zapisem."
                ),
                "findings": findings,
            },
        )
    return about


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
    about_given = "about" in data.model_fields_set
    about = await _clean_about(db, current_user, data.about) if about_given else None
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
        target = owner
    elif own is None:
        target = _new_recruiter_link(current_user.id, slug)
        db.add(target)
    else:
        if own.slug != slug:
            own.slug = slug
        target = own
    if about_given:
        target.about = about
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
    preview_kwargs = {
        "title": effective_title,
        "link_slug": await _preview_slug(db, user, job.id),
        "subtitle": subtitle,
        "about": about,
        "sections": sections,
    }
    # Podgląd (karta LinkedIna w edytorze) = to, co zobaczy kandydat, więc bez
    # sekcji ukrytych; kontrola czyta pełną projekcję (runda 8).
    preview = jpp.public_job_payload(job, **preview_kwargs)
    findings = await jpp.lint_payload(
        db, job, jpp.public_job_payload(job, **preview_kwargs, respect_show=False)
    )
    approved_by_name: Optional[str] = None
    if profile is not None and profile.approved_by:
        approved_by_name = await db.scalar(
            select(User.name).where(User.id == profile.approved_by)
        )
    version = await jpp.published_version(db, job, profile)
    live = (
        PublicProfileLive(
            title=version.title,
            subtitle=version.subtitle,
            about=version.about,
            sections=PublicSections(**jpp.normalize_sections(version.sections)),
            pending_changes=version.pending_changes,
        )
        if version is not None
        else None
    )
    theme_default = ct.default_theme(
        effective_title, await ct.job_category_slug(db, job)
    )
    return PublicProfileResponse(
        live=live,
        theme=profile.theme if profile else None,
        theme_default=theme_default,
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
        approved_content_stale=(
            status_value == jpp.STATUS_APPROVED
            and jpp.approved_content_stale(job, profile.sections if profile else None)
        ),
        findings=[f.as_dict() for f in findings],
        preview=preview,
    )


@router.get("/jobs/{job_id}/public-profile", response_model=PublicProfileResponse)
async def get_public_profile(
    job_id: int, current_user: OperationalUser, db: AsyncSession = Depends(get_db)
) -> PublicProfileResponse:
    job = await _load_job(db, current_user, job_id)
    profile = await db.get(JobPublicProfile, job_id)
    return await _profile_response(db, current_user, job, profile)


@router.get("/jobs/{job_id}/public-profile/poster.pdf")
async def get_public_profile_poster(
    job_id: int, current_user: OperationalUser, db: AsyncSession = Depends(get_db)
) -> Response:
    """Plakat A4 z kodem QR do linku rekrutacji (etap 3 linków, 19.10.2026).

    Treść z opublikowanej wersji opisu, adres = link osoby (albo najnowszy
    aktywny link rekrutacji). 409, gdy strona jeszcze nie działa — plakat bez
    zatwierdzonego opisu prowadziłby kandydata na 404.
    """
    from app.services.career_poster import render_poster_pdf
    from app.services.career_slugs import job_link_url

    job = await _load_job(db, current_user, job_id)
    profile = await db.get(JobPublicProfile, job_id)
    version = await jpp.published_version(db, job, profile)
    slug = await _preview_slug(db, current_user, job_id)
    if version is None or slug is None or not jpp.job_is_open(job):
        raise HTTPException(
            status_code=409,
            detail=(
                "Plakat powstaje z działającej strony rekrutacji — zatwierdź opis "
                "publiczny i wygeneruj link."
            ),
        )
    payload = jpp.public_job_payload(
        job,
        title=version.title,
        link_slug=slug,
        subtitle=version.subtitle,
        about=version.about,
        sections=version.sections,
    )
    theme = ct.resolve_theme(
        profile.theme, version.title, await ct.job_category_slug(db, job)
    )
    pdf = render_poster_pdf(payload, job_link_url(slug), theme=theme)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="plakat-{slug}.pdf"',
            "Cache-Control": "no-store",
        },
    )


@router.put("/jobs/{job_id}/public-profile", response_model=PublicProfileResponse)
async def put_public_profile(
    job_id: int,
    data: PublicProfileUpdate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> PublicProfileResponse:
    """Zapis szkicu. Zmiana treści po zatwierdzeniu = status ``draft``.

    Nie trzeba niczego odznaczać: status wynika ze skrótu treści, a skrót
    zatwierdzonej wersji przestaje pasować przy pierwszej zmianie. Strona
    zostaje na wersji zatwierdzonej (``jpp.published_version``).
    """
    job = await _load_job(db, current_user, job_id)
    profile = await db.get(JobPublicProfile, job_id)
    if profile is None:
        profile = JobPublicProfile(job_id=job_id)
        db.add(profile)
    else:
        await jpp.keep_published_text(db, job, profile)
    fields = data.model_fields_set
    # Znaki formatujące (kategoria Cf) wycinamy jak w ogłoszeniu na portale:
    # „\u202ełz 081\u202c” przeglądarka pokazuje jako „180 zł”, a kontrola
    # porównuje tekst bez nich i go przepuszczała (audyt 13.10.2026).
    if "public_title" in fields:
        title = " ".join(visible(data.public_title or "").split())
        profile.public_title = title[: jpp.PUBLIC_TITLE_MAX] or None
    if "subtitle" in fields:
        profile.subtitle = visible(data.subtitle or "").strip() or None
    if "about" in fields:
        profile.about = visible(data.about or "").strip() or None
    if "sections" in fields and data.sections is not None:
        # Migawka zatwierdzenia zostaje — zmiana przełączników i tak zmienia
        # skrót treści (szkic), a ten sam zestaw nie może zgubić migawki.
        profile.sections = jpp.sections_with_approved_content(
            data.sections.model_dump(), jpp.stored_approved_content(profile.sections)
        )
    elif profile.sections is None:
        profile.sections = jpp.normalize_sections(None)
    if "show_on_recruiter_page" in fields and data.show_on_recruiter_page is not None:
        profile.show_on_recruiter_page = data.show_on_recruiter_page
    if "theme" in fields:
        # Wygląd nie wchodzi do skrótu treści — zatwierdzony opis zostaje.
        profile.theme = data.theme
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
    try:
        await jpp.approve_profile(db, job, profile, user_id=current_user.id)
    except jpp.ProfileFindings as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PUBLIC_PROFILE_FINDINGS",
                "message": (
                    "Opis zawiera treści, których nie publikujemy — popraw je "
                    "przed zatwierdzeniem."
                ),
                "findings": [f.as_dict() for f in exc.findings],
            },
        ) from exc
    await db.commit()
    await db.refresh(profile)
    return await _profile_response(db, current_user, job, profile)
