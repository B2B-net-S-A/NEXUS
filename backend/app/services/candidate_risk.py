"""Candidate Risk computation service.

Liczy historyczne wycofania kandydata z procesów rekrutacyjnych w 24-miesięcznym
oknie i klasyfikuje je do 3 kategorii (early / interview / post_accept) z różnymi
wagami. Wynik (score + level) cache'ujemy w `candidate_risk_profile`.

Wywołanie:
    - `on_candidate_stage_change(db, candidate_id)` — z handlerów tranzycji
      stage'u (event-driven refresh).
    - `get_or_compute(db, candidate_id)` — z endpointu GET /candidates/{id}/risk
      (czyta cache; przelicza gdy stale_after < now() lub brak rekordu).

Filozofia kategoryzacji:
    Patrzymy na stage POPRZEDZAJĄCY ruch na `withdrawn` (nie sam stage='withdrawn',
    bo to zawsze terminal). To pozwala odróżnić "wycofał się w nowym" od "wycofał
    się po akceptacji oferty". `candidate_offer_response='declined'` jest dodatkowym
    warunkiem dla post_accept — bez niego ruchy z acceptance/negotiation/onboarding
    są ignorowane (mogą oznaczać błąd usera albo wycofanie z innego powodu).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate_risk import (
    CandidateOfferResponse,
    CandidateRiskProfile,
    RiskLevel,
)
from app.models.job import Job
from app.models.pipeline_template import RejectionReason
from app.models.recruitment_pipeline import CandidateStage, PipelineStage


logger = logging.getLogger(__name__)


# ── Configuration constants ──────────────────────────────────────────────────

EARLY_STAGES: frozenset[PipelineStage] = frozenset(
    {
        PipelineStage.new,
        PipelineStage.prep_call,
        PipelineStage.screening,
        PipelineStage.verified,
    }
)
INTERVIEW_STAGES: frozenset[PipelineStage] = frozenset(
    {
        PipelineStage.interview,
        PipelineStage.cv_sent,
        PipelineStage.client_interview,
    }
)
POST_ACCEPT_STAGES: frozenset[PipelineStage] = frozenset(
    {
        PipelineStage.acceptance,
        PipelineStage.negotiation,
        PipelineStage.onboarding,
    }
)

POINTS: dict[str, int] = {"early": 1, "interview": 3, "post_accept": 10}
WINDOW_MONTHS = 24
TTL_HOURS = 24
RECENT_EVENTS_LIMIT = 5
LEGACY_REASON_NAME = "legacy_unknown"


# ── Pure helpers ─────────────────────────────────────────────────────────────


def _level_from_score(score: int) -> RiskLevel:
    """Score → level mapping (zgodne z planem: 0-2=low, 3-9=medium, 10+=high)."""
    if score >= 10:
        return RiskLevel.high
    if score >= 3:
        return RiskLevel.medium
    return RiskLevel.low


def _categorize(
    prev_stage: Optional[PipelineStage],
    offer_response: Optional[CandidateOfferResponse],
) -> Optional[str]:
    """Map the stage that PRECEDED a withdrawal into a risk category."""
    if prev_stage is None:
        return None
    if prev_stage in EARLY_STAGES:
        return "early"
    if prev_stage in INTERVIEW_STAGES:
        return "interview"
    if (
        prev_stage in POST_ACCEPT_STAGES
        and offer_response == CandidateOfferResponse.declined
    ):
        return "post_accept"
    return None  # nie liczymy (np. acceptance bez declined response)


# ── Core logic ───────────────────────────────────────────────────────────────


async def _previous_stage_for(
    db: AsyncSession, withdrawal: CandidateStage
) -> Optional[PipelineStage]:
    """Znajdź stage tuż przed `withdrawn` w tym samym (candidate_id, job_id)."""
    stmt = (
        select(CandidateStage.stage)
        .where(
            CandidateStage.candidate_id == withdrawal.candidate_id,
            CandidateStage.job_id == withdrawal.job_id,
            CandidateStage.id != withdrawal.id,
            CandidateStage.moved_at < withdrawal.moved_at,
        )
        .order_by(CandidateStage.moved_at.desc())
        .limit(1)
    )
    return await db.scalar(stmt)


def _empty_summary(candidate_id: int) -> dict:
    """Synth profile dla nowych kandydatów / fallback przy błędach DB.

    Read-path NIGDY nie crashuje — zwraca pustą strukturę. Plain dict
    (nie CandidateRiskProfile) bo nie chcemy nawet allocate'ować ORM modelu
    gdy DB layer się sypie (np. tabeli nie ma jeszcze).
    """
    return {
        "level": RiskLevel.low,
        "score": 0,
        "early_count": 0,
        "interview_count": 0,
        "post_accept_count": 0,
        "recent_events": [],
        "computed_at": datetime.now(timezone.utc),
    }


async def _gather_events(
    db: AsyncSession, candidate_id: int
) -> tuple[dict, list[dict]]:
    """Pure compute — zwraca (counts, events) bez side-effectów na DB."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * WINDOW_MONTHS)

    stmt = (
        select(
            CandidateStage,
            RejectionReason.name.label("reason_name"),
            Job.title.label("job_title"),
        )
        .join(
            RejectionReason,
            CandidateStage.rejection_reason_id == RejectionReason.id,
            isouter=True,
        )
        .join(Job, CandidateStage.job_id == Job.id, isouter=True)
        .where(
            and_(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.stage == PipelineStage.withdrawn,
                CandidateStage.moved_at >= cutoff,
            )
        )
        .order_by(CandidateStage.moved_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    counts = {"early": 0, "interview": 0, "post_accept": 0}
    events: list[dict] = []

    for stage_row, reason_name, job_title in rows:
        if reason_name == LEGACY_REASON_NAME:
            continue
        prev_stage = await _previous_stage_for(db, stage_row)
        category = _categorize(prev_stage, stage_row.candidate_offer_response)
        if category is None:
            continue
        counts[category] += 1
        events.append(
            {
                "job_id": stage_row.job_id,
                "moved_at": stage_row.moved_at.isoformat(),
                "category": category,
                "reason": reason_name or "unknown",
                "job_title": job_title,
            }
        )

    return counts, events


async def compute_summary(db: AsyncSession, candidate_id: int) -> dict:
    """READ-ONLY compute. Zwraca dict bez touch'a DB write. Nie crashuje
    nigdy — przy błędach SQL fallback do pustego summary."""
    try:
        counts, events = await _gather_events(db, candidate_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "compute_summary read failed for candidate=%s: %s", candidate_id, exc
        )
        return _empty_summary(candidate_id)

    score = sum(counts[k] * POINTS[k] for k in counts)
    return {
        "level": _level_from_score(score),
        "score": score,
        "early_count": counts["early"],
        "interview_count": counts["interview"],
        "post_accept_count": counts["post_accept"],
        "recent_events": events[:RECENT_EVENTS_LIMIT],
        "computed_at": datetime.now(timezone.utc),
    }


async def compute_risk(
    db: AsyncSession, candidate_id: int
) -> CandidateRiskProfile:
    """Pełna kalkulacja + UPSERT do cache. Wywoływana z hooka tranzycji.

    Może crash'ować jeśli tabela `candidate_risk_profile` nie istnieje
    (migracja nie zaaplikowana) — wtedy `on_candidate_stage_change` łapie
    w try/except i loguje warning. Read-path używa `compute_summary`.
    """
    summary = await compute_summary(db, candidate_id)

    profile = await db.get(CandidateRiskProfile, candidate_id)
    if profile is None:
        profile = CandidateRiskProfile(candidate_id=candidate_id)
        db.add(profile)

    profile.level = summary["level"]
    profile.score = summary["score"]
    profile.early_count = summary["early_count"]
    profile.interview_count = summary["interview_count"]
    profile.post_accept_count = summary["post_accept_count"]
    profile.recent_events = summary["recent_events"]
    profile.computed_at = summary["computed_at"]
    profile.stale_after = summary["computed_at"] + timedelta(hours=TTL_HOURS)

    await db.flush()
    return profile


async def on_candidate_stage_change(
    db: AsyncSession, candidate_id: int
) -> None:
    """Hook wołany z handlerów tranzycji stage'u. Best-effort — nie blokuje commitu.

    Idempotentny: można wywołać wielokrotnie. Recompute na każdej tranzycji nie
    tylko withdrawn — bo np. cofnięcie z withdrawn też powinno zaktualizować score.
    """
    try:
        await compute_risk(db, candidate_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "compute_risk failed for candidate=%s: %s", candidate_id, exc
        )


async def get_or_compute(
    db: AsyncSession, candidate_id: int
) -> CandidateRiskProfile:
    """[Legacy compat] Czyta cache; przelicza gdy brak lub TTL minął.

    Read-path API używa `compute_summary` zamiast tego (read-only, defensive).
    """
    try:
        profile = await db.get(CandidateRiskProfile, candidate_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "risk profile lookup failed candidate=%s: %s", candidate_id, exc
        )
        return None  # type: ignore[return-value]
    if profile is None:
        return await compute_risk(db, candidate_id)
    if profile.stale_after is None or profile.stale_after < datetime.now(
        timezone.utc
    ):
        return await compute_risk(db, candidate_id)
    return profile
