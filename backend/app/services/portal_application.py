"""Aplikacja z formularza portalu do rekrutacji ogłoszenia (06.11.2026).

Decyzja Artura z 06.11.2026: kandydat aplikuje formularzem JustJoin.IT
(jedno kliknięcie, CV zostaje w panelu pracodawcy), a NEXUS sam zakłada mu
kartę w „Nowi” rekrutacji, na którą aplikował. Do tej daty import z panelu
(scraper na Macu) znał tylko tytuł ogłoszenia: profil trafiał do bazy, a
karta powstawała wyłącznie z auto-matcha CV, zwykle w innej rekrutacji.
Pomiar na kopii produkcji z 06.11: 1 690 z 2 159 aplikacji z 30 dni bez
karty w żadnej rekrutacji.

Rekrutację ogłoszenia wyznacza:

1. ``job_postings.external_id`` = id ogłoszenia (UUID), gdy ogłoszenie
   poszło z NEXUSA przez API (ten sam id widzi panel pracodawcy),
2. slug z linku ``job_ad_publications.url`` („Oznacz jako opublikowane”),
   gdy ogłoszenie wklejono ręcznie.

Kartę zakłada ``add_candidates_to_job``, czyli te same bramki co rekruter
(czarna lista, NDA i konflikty klienta, weto hiring managera, już w procesie).
Źródło „ogłoszenie” z ``job_id`` to jednocześnie dowód zgłoszenia, który czyta
``integration_intake``, więc późniejsze ``proposals/bulk`` od integracji
też nie zamieni tej osoby w propozycję.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel
from app.models.job import Job, JobStatus
from app.models.job_ad_publication import JobAdPublication
from app.models.job_posting import JobPosting, Portal

logger = logging.getLogger(__name__)

#: Portale importu z panelu 1EP. RocketJobs nie zapisuje „gdzie wisi”
#: (``job_ad_publications`` zna tylko ``pracuj`` i ``jjit``), więc jego
#: ogłoszenie rozpoznajemy wyłącznie po id z publikacji przez API.
PORTALS = {"justjoinit": Portal.justjoinit, "rocketjobs": Portal.rocketjobs}
_PUBLICATION_PORTAL = {"justjoinit": "jjit"}
_PORTAL_LABEL = {"justjoinit": "JustJoin.IT", "rocketjobs": "RocketJobs"}
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,299}$")


@dataclass(frozen=True)
class PortalApplicationResult:
    """``outcome``: ``added`` · ``already_in_job`` · ``skipped`` · ``no_job`` · ``job_not_open``."""

    outcome: str
    job_id: Optional[int] = None
    stage_id: Optional[int] = None
    reason: Optional[str] = None


def slug_from_url(url: Optional[str]) -> Optional[str]:
    """Ostatni człon ścieżki linku ogłoszenia (``…/job-offer/<slug>``)."""
    if not url:
        return None
    path = url.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    slug = path.rsplit("/", 1)[-1].lower()
    return slug if _SLUG_RE.match(slug) else None


def normalize_slug(value: Optional[str]) -> Optional[str]:
    """Slug z panelu albo cały link — zawsze sam slug albo ``None``."""
    if not value:
        return None
    value = value.strip()
    if "/" in value:
        return slug_from_url(value)
    value = value.lower()
    return value if _SLUG_RE.match(value) else None


async def resolve_job_id(
    db: AsyncSession, *, portal: str, ad_id: str, ad_slug: Optional[str]
) -> Optional[int]:
    """Rekrutacja ogłoszenia: najpierw id z publikacji przez API, potem slug."""
    job_id = await db.scalar(
        select(JobPosting.job_id)
        .where(JobPosting.portal == PORTALS[portal], JobPosting.external_id == ad_id)
        .order_by(JobPosting.id.desc())
        .limit(1)
    )
    if job_id is not None:
        return int(job_id)
    slug = normalize_slug(ad_slug)
    publication_portal = _PUBLICATION_PORTAL.get(portal)
    if slug is None or publication_portal is None:
        return None
    rows = (
        await db.execute(
            select(JobAdPublication.job_id, JobAdPublication.url)
            .where(
                JobAdPublication.portal == publication_portal,
                JobAdPublication.removed_at.is_(None),
                JobAdPublication.url.ilike(f"%{slug}%"),
            )
            .order_by(JobAdPublication.published_at.desc())
        )
    ).all()
    for row in rows:
        if slug_from_url(row.url) == slug:
            return int(row.job_id)
    return None


async def _record_source(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    portal: str,
    ad_title: Optional[str],
    applied_at: Optional[datetime],
) -> None:
    exists = await db.scalar(
        select(CandidateSourceEvent.id).where(
            CandidateSourceEvent.candidate_id == candidate_id,
            CandidateSourceEvent.job_id == job_id,
            CandidateSourceEvent.channel == SourceChannel.posting,
        )
    )
    if exists is not None:
        return
    label = _PORTAL_LABEL[portal]
    note = f"Aplikacja przez {label}"
    if ad_title:
        note += f" — ogłoszenie: {ad_title}"
    db.add(
        CandidateSourceEvent(
            candidate_id=candidate_id,
            job_id=job_id,
            channel=SourceChannel.posting,
            utm_source="jjit" if portal == "justjoinit" else portal,
            utm_medium="job_board",
            note=note[:500],
            captured_at=applied_at or datetime.now(timezone.utc),
        )
    )
    await db.flush()


async def place_application(
    db: AsyncSession,
    *,
    candidate_id: int,
    portal: str,
    ad_id: str,
    ad_slug: Optional[str] = None,
    ad_title: Optional[str] = None,
    applied_at: Optional[datetime] = None,
) -> PortalApplicationResult:
    """Źródło z ``job_id`` i karta w „Nowi” rekrutacji ogłoszenia. Bez commita."""
    from app.api.proposals_bulk import add_candidates_to_job  # noqa: PLC0415
    from app.services import candidate_claim  # noqa: PLC0415

    job_id = await resolve_job_id(db, portal=portal, ad_id=ad_id, ad_slug=ad_slug)
    if job_id is None:
        return PortalApplicationResult(outcome="no_job")
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        return PortalApplicationResult(outcome="no_job")
    await _record_source(
        db,
        candidate_id=candidate_id,
        job_id=job.id,
        portal=portal,
        ad_title=ad_title,
        applied_at=applied_at,
    )
    if job.status != JobStatus.published:
        return PortalApplicationResult(outcome="job_not_open", job_id=job.id)

    result = await add_candidates_to_job(
        db,
        job=job,
        candidate_ids=[candidate_id],
        actor_user_id=job.recruiter_id,
        note=f"Aplikacja przez {_PORTAL_LABEL[portal]}",
        entry_source=candidate_claim.ENTRY_APPLICATION,
        claim=False,
        mark_proposals=False,
    )
    if candidate_id in result.added:
        return PortalApplicationResult(
            outcome="added", job_id=job.id, stage_id=result.stage_ids.get(candidate_id)
        )
    skipped = next((s for s in result.skipped if s.candidate_id == candidate_id), None)
    reason = skipped.reason if skipped is not None else None
    reason_value = getattr(reason, "value", reason)
    if reason_value == "already_in_job":
        return PortalApplicationResult(outcome="already_in_job", job_id=job.id)
    return PortalApplicationResult(
        outcome="skipped",
        job_id=job.id,
        reason=(skipped.reason_label if skipped is not None else None) or reason_value,
    )


async def notify_recruiter(
    db: AsyncSession, *, job_id: int, candidate_id: int, portal: str
) -> None:
    """Dzwonek „nowe zgłoszenie” dla prowadzącego, w razie braku — dla DL. Nie rzuca."""
    try:
        from app.models.candidate import Candidate  # noqa: PLC0415
        from app.models.notification import NotificationType  # noqa: PLC0415
        from app.services.job_previous_recruiters import (  # noqa: PLC0415
            working_owner_id,
        )
        from app.services.notification_triggers import emit  # noqa: PLC0415

        job = await db.scalar(select(Job).where(Job.id == job_id))
        if job is None:
            return
        user_id = await working_owner_id(db, job) or job.delivery_lead_id
        if user_id is None:
            return
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == candidate_id)
        )
        who = (
            f"{candidate.name or ''} {candidate.lastname or ''}".strip()
            if candidate is not None
            else ""
        ) or "Nowa osoba"
        await emit(
            db,
            user_id=user_id,
            title=f"Nowa aplikacja z {_PORTAL_LABEL[portal]}",
            message=f"{who} aplikował(a) na „{job.title}”. Karta czeka w „Nowi”.",
            ntype=NotificationType.new_application,
            related_entity_type="candidate",
            related_entity_id=candidate_id,
            link=f"/jobs/{job.id}",
        )
        await db.commit()
    except Exception:  # noqa: BLE001 - dzwonek nie może cofnąć karty
        logger.exception(
            "[portal-application] notify failed job=%s candidate=%s",
            job_id,
            candidate_id,
        )
