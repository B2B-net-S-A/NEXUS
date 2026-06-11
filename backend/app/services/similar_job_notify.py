"""Szybkie przepinanie — Faza 1: proaktywna notyfikacja po utworzeniu joba.

Gdy powstaje nowy request, sprawdzamy (w background tasku, po wygenerowaniu
embeddingu) czy istnieją semantycznie podobne historyczne requesty (Tier A,
cosine >= 0.70), na których kandydaci doszli do etapów klienckich
(``CLIENT_FACING_STAGES``). Jeśli tak — recruiter/TAC/twórca joba dostają
in-app notyfikację z deep-linkiem do sekcji „Kandydaci z podobnych projektów"
(`/jobs/{id}?tab=similar`), skąd przepinają ludzi jednym bulk-klikiem.

Zasady anty-szumowe:
- tylko kandydaci z Tier A źródłem (mocne podobieństwo requestów),
- tylko z historią kliencką (cv_sent+), nie sam screening,
- kandydaci odrzuceni wcześniej u TEGO klienta nie liczą się do progu,
- dedup per (user, type, job, dzień) przez ``ix_notif_dedup_daily``,
- kill-switch ``SIMILAR_JOB_NOTIFY_ENABLED`` bez redeploya.

Wzorzec sesji/backgroundu: `run_marketplace_scan_safe` (własna sesja, bo
FastAPI zamyka requestową zanim background task pobiegnie).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import AvailabilityStatus, Candidate
from app.models.job import Job
from app.models.notification import NotificationType
from app.services.notification_triggers import emit
from app.services.similar_job_candidates import (
    CLIENT_FACING_STAGES,
    HistoricalCandidate,
    SimilarJobRef,
    fetch_historical_candidates,
)

logger = logging.getLogger(__name__)

_AVAILABLE_STATUSES = {
    AvailabilityStatus.actively_looking,
    AvailabilityStatus.open_to_offers,
}


@dataclass(frozen=True)
class SimilarJobAlert:
    """Decyzja „czy i co wysłać" — czysta, testowalna bez DB."""

    candidate_ids: tuple[int, ...]
    same_client_count: int
    top_similar_title: str
    top_similarity: float


def build_alert(
    ranked: Sequence[HistoricalCandidate],
    similar_refs: Sequence[SimilarJobRef],
) -> Optional[SimilarJobAlert]:
    """Zwraca treściwy alert albo None, gdy sygnał jest za słaby.

    „Mocny" kandydat = Tier A + co najmniej jedno klienckie źródło
    (cv_sent/client_interview/…/hired) + nie został odrzucony u klienta,
    dla którego właśnie rekrutujemy.
    """
    strong = [
        c
        for c in ranked
        if c.tier == "A"
        and not c.rejected_by_same_client
        and any(s.stage in CLIENT_FACING_STAGES for s in c.sources)
    ]
    if len(strong) < settings.SIMILAR_JOB_NOTIFY_MIN_CANDIDATES:
        return None

    tier_a_refs = [r for r in similar_refs if r.tier == "A"]
    if not tier_a_refs:
        return None
    top_ref = max(tier_a_refs, key=lambda r: r.similarity)

    return SimilarJobAlert(
        candidate_ids=tuple(c.candidate_id for c in strong),
        same_client_count=sum(1 for c in strong if c.same_client),
        top_similar_title=top_ref.title,
        top_similarity=top_ref.similarity,
    )


def build_message(job_title: str, alert: SimilarJobAlert, available_count: int) -> str:
    """Treść notyfikacji — po polsku, z konkretami zamiast ogólników."""
    n = len(alert.candidate_ids)
    parts = [
        f"Request „{job_title}” wygląda jak „{alert.top_similar_title}” "
        f"(podobieństwo {round(alert.top_similarity * 100)}%). "
        f"{n} kandydat(ów) poszło już do klienta na podobnych requestach"
    ]
    if alert.same_client_count:
        parts.append(f", w tym {alert.same_client_count} u tego klienta")
    if available_count:
        parts.append(f"; {available_count} oznaczonych jako dostępni")
    parts.append(
        ". Otwórz „Kandydaci z podobnych projektów” i przepnij ich jednym kliknięciem."
    )
    return "".join(parts)


async def notify_similar_job_candidates(db: AsyncSession, job_id: int) -> int:
    """Sprawdź podobieństwo i wyemituj notyfikacje. Zwraca liczbę emisji."""
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        return 0

    ranked, similar_refs, _tier_used = await fetch_historical_candidates(
        db,
        job_id,
        tier="primary",
        limit=50,
        include_negative=True,
        target_client_id=job.client_id,
    )
    alert = build_alert(ranked, similar_refs)
    if alert is None:
        return 0

    avail_rows = await db.execute(
        select(Candidate.availability_status).where(
            Candidate.id.in_(alert.candidate_ids)
        )
    )
    available_count = sum(
        1 for (status,) in avail_rows.all() if status in _AVAILABLE_STATUSES
    )

    recipients = {job.recruiter_id, job.tac_id, job.created_by} - {None}
    if not recipients:
        return 0

    message = build_message(job.title, alert, available_count)
    emitted = 0
    for user_id in recipients:
        result = await emit(
            db,
            user_id=user_id,
            title="Podobny request — gotowi kandydaci do przepięcia",
            message=message,
            ntype=NotificationType.similar_job_candidates,
            related_entity_type="job",
            related_entity_id=job.id,
            link=f"/jobs/{job.id}?tab=similar",
        )
        if result is not None:
            emitted += 1
    return emitted


async def run_similar_job_notify_safe(job_id: int) -> None:
    """Wrapper pod `BackgroundTasks.add_task(...)` — własna sesja + try/except."""
    if not settings.SIMILAR_JOB_NOTIFY_ENABLED:
        return
    try:
        async with AsyncSessionLocal() as db:
            emitted = await notify_similar_job_candidates(db, job_id)
            await db.commit()
            if emitted:
                logger.info(
                    "[SimilarJobNotify] job=%s emitted=%s notifications",
                    job_id,
                    emitted,
                )
    except Exception:
        logger.exception("run_similar_job_notify_safe failed job_id=%d", job_id)
