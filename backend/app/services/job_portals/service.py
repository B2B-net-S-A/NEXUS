"""Kolejka publikacji rekrutacji na portalach (0360).

Zgłoszenie publikacji (``request_publish``) zapisuje wiersz ``publishing``;
worker (``process_batch``) bierze wiersze ``FOR UPDATE SKIP LOCKED`` (wzór
``index_outbox_service.claim_batch``) i woła adapter. Odmowy przed kolejką:

* portal wyłączony / bez konfiguracji → 409 (nic się nie zapisuje);
* brak ZATWIERDZONEGO opisu publicznego → 409 — do portalu idzie wyłącznie
  biała lista z ``job_public_profile.public_job_payload`` (nigdy klient ani
  stawka, jak na stronie kariery);
* brak aktywnego linku aplikacyjnego rekrutacji → 409 — kandydat z portalu
  aplikuje przez stronę kariery (``/r/<slug>``), więc zgłoszenie trafia do tej
  samej ścieżki co z LinkedIna;
* żywa publikacja na tym portalu już jest → 409 (i częściowy UNIQUE w bazie).
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job
from app.models.job_posting import JobPosting, Portal, PostingStatus
from app.models.job_public_profile import JobPublicProfile
from app.services import job_portals
from app.services.job_portals.base import PortalError, PostingContent

logger = logging.getLogger(__name__)

LIVE_STATUSES = (PostingStatus.publishing, PostingStatus.published)


class PortalRequestError(Exception):
    """Odmowa zgłoszenia (409/422) z komunikatem po polsku."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


@dataclass(frozen=True)
class BuiltContent:
    content: PostingContent
    profile_hash: str
    payload_hash: str


async def _job_link_slug(db: AsyncSession, job_id: int) -> Optional[str]:
    now = datetime.now(timezone.utc)
    rows = (
        await db.scalars(
            select(CandidateInviteLink)
            .where(
                CandidateInviteLink.job_id == job_id,
                CandidateInviteLink.kind == "job",
                CandidateInviteLink.revoked.is_(False),
                CandidateInviteLink.slug.is_not(None),
            )
            .order_by(CandidateInviteLink.created_at.desc())
        )
    ).all()
    for link in rows:
        if link.expires_at is None or link.expires_at > now:
            return link.slug
    return None


async def build_content(db: AsyncSession, job: Job) -> BuiltContent:
    """Treść ogłoszenia albo odmowa — wyłącznie z zatwierdzonego opisu."""

    from app.services.career_slugs import job_link_url
    from app.services.job_public_profile import (
        STATUS_APPROVED,
        public_job_payload,
        resolve_status,
    )

    profile = await db.scalar(
        select(JobPublicProfile).where(JobPublicProfile.job_id == job.id)
    )
    status, _default, title = await resolve_status(db, job, profile)
    if profile is None or status != STATUS_APPROVED:
        raise PortalRequestError(
            409,
            "public_profile_not_approved",
            "Rekrutacja nie ma zatwierdzonego opisu publicznego — zatwierdź go "
            "w „Stronie kariery”, zanim wyślesz ogłoszenie na portal.",
        )
    slug = await _job_link_slug(db, job.id)
    if not slug:
        raise PortalRequestError(
            409,
            "job_link_missing",
            "Rekrutacja nie ma aktywnego linku aplikacyjnego — utwórz link na "
            "stronie kariery; kandydaci z portalu aplikują przez niego.",
        )
    payload = public_job_payload(
        job,
        title=title,
        link_slug=slug,
        subtitle=profile.subtitle,
        about=profile.about,
        sections=profile.sections,
    )
    content = PostingContent(title=title, job=payload, apply_url=job_link_url(slug))
    encoded = json.dumps(
        {"job": payload, "apply_url": content.apply_url},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return BuiltContent(
        content=content,
        profile_hash=profile.approved_hash or "",
        payload_hash=hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
    )


def _ensure_portal_ready(portal: Portal) -> None:
    if portal not in job_portals.ADAPTERS:
        raise PortalRequestError(
            422, "portal_unsupported", "Ten portal nie ma integracji w NEXUSIE."
        )
    config = job_portals.PortalConfig.from_settings(portal)
    if config.state != "ready":
        raise PortalRequestError(
            409,
            "portal_not_configured",
            "Portal nie jest skonfigurowany — publikacja jest niedostępna.",
        )


async def request_publish(
    db: AsyncSession, *, job: Job, portal: Portal, user_id: Optional[int]
) -> JobPosting:
    _ensure_portal_ready(portal)
    live = await db.scalar(
        select(JobPosting.id).where(
            JobPosting.job_id == job.id,
            JobPosting.portal == portal,
            JobPosting.status.in_(LIVE_STATUSES),
        )
    )
    if live is not None:
        raise PortalRequestError(
            409,
            "posting_already_live",
            "Ogłoszenie tej rekrutacji na tym portalu już jest publikowane.",
        )
    built = await build_content(db, job)
    posting = JobPosting(
        job_id=job.id,
        portal=portal,
        status=PostingStatus.publishing,
        attempts=0,
        payload_hash=built.payload_hash,
        public_profile_hash=built.profile_hash,
        created_by=user_id,
    )
    db.add(posting)
    await db.flush()
    return posting


async def request_unpublish(
    db: AsyncSession, *, job: Job, portal: Portal
) -> Optional[JobPosting]:
    """Wycofanie: wiersz ``publishing`` (worker go nie wziął) = od razu ``removed``.

    Opublikowany wymaga adaptera — przy wyłączonym portalu 409, bo wycofanie
    „na niby” zostawiłoby ogłoszenie wiszące na portalu.
    """

    posting = await db.scalar(
        select(JobPosting)
        .where(
            JobPosting.job_id == job.id,
            JobPosting.portal == portal,
            JobPosting.status.in_(LIVE_STATUSES),
        )
        .with_for_update()
    )
    if posting is None:
        return None
    if posting.status == PostingStatus.publishing:
        posting.status = PostingStatus.removed
        posting.last_error = None
        return posting
    _ensure_portal_ready(portal)
    adapter = job_portals.adapter_for(portal)
    try:
        if posting.external_id:
            await adapter.unpublish(posting.external_id)
    except PortalError as exc:
        raise PortalRequestError(409, "portal_refused", exc.message) from exc
    posting.status = PostingStatus.removed
    posting.last_synced_at = datetime.now(timezone.utc)
    return posting


async def claim_batch(db: AsyncSession, limit: int) -> list[JobPosting]:
    return list(
        (
            await db.scalars(
                select(JobPosting)
                .where(JobPosting.status == PostingStatus.publishing)
                .order_by(JobPosting.id.asc())
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )


async def process_posting(db: AsyncSession, posting: JobPosting) -> None:
    """Jedna publikacja: adapter → ``published`` albo ``failed``/ponowienie."""

    now = datetime.now(timezone.utc)
    posting.attempts = (posting.attempts or 0) + 1
    try:
        job = await db.get(Job, posting.job_id)
        if job is None:
            raise PortalError("Rekrutacja już nie istnieje.")
        built = await build_content(db, job)
        adapter = job_portals.adapter_for(posting.portal)
        result = await adapter.publish(built.content)
    except PortalRequestError as exc:
        posting.status = PostingStatus.failed
        posting.last_error = exc.message
        return
    except PortalError as exc:
        posting.last_error = exc.message
        if not exc.retryable or posting.attempts >= settings.JOB_PORTAL_MAX_ATTEMPTS:
            posting.status = PostingStatus.failed
        return
    posting.status = PostingStatus.published
    posting.external_id = result.external_id
    posting.url = result.url
    posting.published_at = now
    posting.last_synced_at = now
    posting.last_error = None
    posting.payload_hash = built.payload_hash
    posting.public_profile_hash = built.profile_hash


async def process_batch(db: AsyncSession, limit: int = 10) -> int:
    postings = await claim_batch(db, limit)
    for posting in postings:
        await process_posting(db, posting)
    return len(postings)


async def failed_recently(db: AsyncSession, *, hours: int = 24) -> int:
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    return int(
        await db.scalar(
            select(func.count(JobPosting.id)).where(
                JobPosting.status == PostingStatus.failed,
                JobPosting.updated_at >= since,
            )
        )
        or 0
    )
