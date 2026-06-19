"""Auto-add candidate to a talent pool when CV is sent to the client.

Trigger: stage change → PipelineStage.cv_sent (handled in
`app.api.pipeline.move_candidate`). The caller (pipeline endpoint) is
responsible for committing the session — this service only stages inserts
so that the whole stage-change transaction is atomic.

Pool category derivation (based on Job):
  - subcategory + seniority → "{subcategory} {Seniority-label-PL}"
  - only subcategory → "{subcategory}"
  - only seniority   → "{Seniority-label-PL} — Inne"
  - neither          → skip (logged via Activity as `pool_skip_no_category`)

Competence Category assignment (Phase 10 A2):
  - New pools inherit `competence_category_id` from `job.competence_category_id`
    (no synchronous classifier call — that would add Qdrant latency to every
    stage-move. Jobs since migration 0041 carry CC directly.)
  - Existing pools with CC=NULL are *opportunistically healed* when a
    CC-bearing job flows through the same pool. Idempotent: second healing
    with the same value is a no-op.
  - Existing pools with CC set are NEVER downgraded.

Idempotency: DB-level UniqueConstraint `uq_pool_candidate` on
(talent_pool_id, candidate_id). Re-trigger of cv_sent for the same pair
results in `AutoAddResult(status="already_in_pool")` without duplication.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.job import Job, Seniority
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.services.talent_pool_cc import resolve_cc_id_for_pool_name

logger = logging.getLogger(__name__)


_SENIORITY_LABELS: dict[Seniority, str] = {
    Seniority.junior: "Junior",
    Seniority.mid: "Mid",
    Seniority.senior: "Senior",
    Seniority.lead: "Lead",
    Seniority.architect: "Architect",
}


def _seniority_label(sen: Seniority) -> str:
    """Return Polish-facing label for a Seniority enum."""
    return _SENIORITY_LABELS.get(sen, sen.value.capitalize())


def _clean(s: Optional[str]) -> Optional[str]:
    """Treat blank/whitespace strings as None."""
    if s is None:
        return None
    stripped = s.strip()
    return stripped or None


def _derive_pool_name(job: Job) -> Optional[str]:
    """Derive a stable, human-readable pool name from a Job.

    Returns None when neither subcategory nor seniority is present — in that
    case the caller should skip the auto-add.
    """
    subcat = _clean(job.subcategory)
    sen = job.seniority
    if subcat and sen:
        return f"{subcat} {_seniority_label(sen)}"
    if subcat:
        return subcat
    if sen:
        return f"{_seniority_label(sen)} — Inne"
    return None


def _resolve_cc_id(job: Job) -> Optional[int]:
    """Return CC id for a Job; None if Job lacks CC assignment.

    No classifier fallback here — that would couple the hot pipeline path to
    Qdrant I/O (see services/cc_classifier.py). Legacy jobs (pre migration
    0041) without CC produce pools without CC; those are healed later by the
    backfill script or opportunistically when a CC-bearing job reuses the
    same pool.
    """
    return getattr(job, "competence_category_id", None)


@dataclass(frozen=True)
class AutoAddResult:
    """Outcome of auto_add_on_cv_sent."""

    status: str  # "added" | "already_in_pool" | "skipped_no_category"
    pool_id: Optional[int] = None
    pool_name: Optional[str] = None
    pool_created: bool = False


async def auto_add_on_cv_sent(
    *,
    db: AsyncSession,
    candidate_id: int,
    job: Job,
    user_id: Optional[int],
    extra_activity_details: Optional[dict] = None,
) -> AutoAddResult:
    """Idempotently add the candidate to a talent pool derived from the Job.

    Does NOT commit — the caller (move_candidate) commits the whole
    stage-change transaction.

    Args:
        extra_activity_details: Optional dict merged into every Activity row's
            `details` JSONB. Used by the backfill script to tag historical
            replays with ``{"backfill": True}`` so dashboards can filter.

    Raises exceptions on unexpected DB errors; the caller should wrap this
    in try/except to avoid blocking the core stage-change operation.
    """
    pool_name = _derive_pool_name(job)
    extra = extra_activity_details or {}

    if pool_name is None:
        db.add(
            Activity(
                entity_type="talent_pool",
                entity_id=job.id or 0,
                action="pool_skip_no_category",
                user_id=user_id,
                details={
                    "candidate_id": candidate_id,
                    "job_id": job.id,
                    "source_event": "cv_sent",
                    "reason": "job_has_no_subcategory_and_no_seniority",
                    **extra,
                },
            )
        )
        return AutoAddResult(status="skipped_no_category")

    # Trigger CV→Klient zawsze celuje w pulę FIRMOWĄ. Filtr `is_personal=False`
    # (+ `is_marketplace=False`) jest kluczowy: nazwy pul nie są unikalne, więc
    # bez niego pula OSOBISTA o kolidującej nazwie (np. „Python Senior") byłaby
    # mutowana przez cudzy ruch na etap cv_sent — z pominięciem gate'a
    # `_assert_can_modify_pool` (właściciel/admin). Patrz migracja 0137.
    pool = await db.scalar(
        select(TalentPool).where(
            TalentPool.name == pool_name,
            TalentPool.is_personal.is_(False),
            TalentPool.is_marketplace.is_(False),
        )
    )

    # Prefer the Job's CC; fall back to a pure name-based classification when
    # the Job has none (true for every legacy job on prod). The fallback is
    # only needed when we're about to create the pool or heal a NULL one, so we
    # skip the lookup for pools that already carry a CC. Still no Qdrant I/O.
    cc_id = _resolve_cc_id(job)
    if cc_id is None and (pool is None or pool.competence_category_id is None):
        cc_id = await resolve_cc_id_for_pool_name(db, pool_name)
    if cc_id is None:
        logger.info(
            "auto_add_on_cv_sent: job=%s + name=%r yielded no competence "
            "category (pool will be created/kept without CC)",
            job.id,
            pool_name,
        )

    pool_created = False
    if pool is None:
        subcat = _clean(job.subcategory)
        sen_value = job.seniority.value if job.seniority else None
        pool = TalentPool(
            name=pool_name,
            description=(
                f"Auto-utworzone przez trigger CV→Klient "
                f"(subcategory={subcat or '-'}, seniority={sen_value or '-'})"
            ),
            criteria={
                "auto_source": "cv_sent_trigger",
                "subcategory": subcat,
                "seniority": sen_value,
            },
            competence_category_id=cc_id,
            created_by=user_id,
        )
        db.add(pool)
        await db.flush()
        pool_created = True
    elif pool.competence_category_id is None and cc_id is not None:
        # Opportunistic healing — legacy pool gains CC when a CC-bearing job
        # flows through. Never downgrade a pool that already has CC set.
        pool.competence_category_id = cc_id

    stmt = (
        pg_insert(TalentPoolMembership.__table__)
        .values(
            talent_pool_id=pool.id,
            candidate_id=candidate_id,
            added_by=user_id,
            source_event="cv_sent",
            source_job_id=job.id,
        )
        .on_conflict_do_nothing(constraint="uq_pool_candidate")
        .returning(TalentPoolMembership.__table__.c.id)
    )
    result = await db.execute(stmt)
    inserted_id = result.scalar()

    if inserted_id is None:
        db.add(
            Activity(
                entity_type="talent_pool",
                entity_id=pool.id,
                action="candidate_already_in_pool",
                user_id=user_id,
                details={
                    "candidate_id": candidate_id,
                    "job_id": job.id,
                    "source_event": "cv_sent",
                    "pool_name": pool.name,
                    **extra,
                },
            )
        )
        return AutoAddResult(
            status="already_in_pool",
            pool_id=pool.id,
            pool_name=pool.name,
            pool_created=False,
        )

    pool.centroid_updated_at = None

    db.add(
        Activity(
            entity_type="talent_pool",
            entity_id=pool.id,
            action="candidate_auto_added",
            user_id=user_id,
            details={
                "candidate_id": candidate_id,
                "job_id": job.id,
                "source_event": "cv_sent",
                "pool_name": pool.name,
                "pool_created": pool_created,
                **extra,
            },
        )
    )

    return AutoAddResult(
        status="added",
        pool_id=pool.id,
        pool_name=pool.name,
        pool_created=pool_created,
    )
