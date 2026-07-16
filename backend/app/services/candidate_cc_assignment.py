"""Shared writer: persist CC classifier scores onto a candidate.

Single source of truth for turning ``classify_candidate_to_cc()`` output into
durable state. Used by BOTH the on-CV-upload auto-assign path
(``_auto_assign_primary_cc`` in ``app.api.candidates``) and the bulk backfill
(``backfill_candidate_ccs`` below, driven by the admin endpoint + CLI script).

It writes the M2M ``candidate_competence_categories`` (1 primary + up to 2
secondary, each with ``confidence_score`` + ``source`` band) AND keeps the
legacy ``candidates.competence_category`` (slug) + ``competence_category_id``
(FK) in sync with the primary — so the list filter, the profile badge and older
call-sites all agree on the same primary category.

Curation safety
---------------
Rows with ``source='manual'`` mean a recruiter curated this profile. The auto
path NEVER touches such a candidate — it bails out entirely and leaves every
assignment as-is. Manual curation always wins over re-classification.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.competence_category import (
    CandidateCcCategorySource,
    CandidateCompetenceCategory,
)
from app.services.cc_classifier import CcScore, classify_candidate_to_cc

logger = logging.getLogger(__name__)

# A primary is written only when the top score clears this bar. The classifier
# already drops everything < 0.30, so this is an explicit belt-and-suspenders.
PRIMARY_MIN_SCORE = 0.30
# Secondary categories need a stronger signal than the primary floor, otherwise
# every candidate collects noisy extra buckets.
SECONDARY_MIN_SCORE = 0.40
# Source band: >= this is a confident auto-assign; below is an AI *suggestion*.
AI_AUTO_MIN_SCORE = 0.80
# Kandydat może mieć 1 primary + do 2 secondary (kontrakt modelu).
MAX_SECONDARY = 2


def _source_for_score(score: float) -> CandidateCcCategorySource:
    return (
        CandidateCcCategorySource.ai_auto
        if score >= AI_AUTO_MIN_SCORE
        else CandidateCcCategorySource.ai_suggested
    )


def _clamp_confidence(score: float) -> float:
    """Keep confidence inside the DB check constraint [0.0, 1.0]."""
    return max(0.0, min(1.0, float(score)))


async def apply_candidate_cc_scores(
    candidate: Candidate,
    scores: list[CcScore],
    db: AsyncSession,
    *,
    overwrite: bool = True,
) -> Optional[dict[str, Any]]:
    """Persist classifier ``scores`` as the candidate's CC assignments.

    Writes the M2M (primary + up to 2 secondary) and syncs the legacy
    ``competence_category`` slug + ``competence_category_id`` FK to the primary.
    Does **not** commit — the caller owns the transaction.

    Returns a small summary dict (``{primary, primary_score, secondary}``) when
    it wrote, or ``None`` when it made no change:
      * no usable signal (empty scores / top below ``PRIMARY_MIN_SCORE``), or
      * the candidate is manually curated (has any ``source='manual'`` row), or
      * ``overwrite=False`` and the candidate already has a primary CC.
    """
    if not scores:
        return None
    top = scores[0]
    if top.score < PRIMARY_MIN_SCORE:
        return None

    existing = (
        (
            await db.execute(
                select(CandidateCompetenceCategory).where(
                    CandidateCompetenceCategory.candidate_id == candidate.id
                )
            )
        )
        .scalars()
        .all()
    )
    # Recruiter-curated profiles are sacred — never override.
    if any(e.source == CandidateCcCategorySource.manual for e in existing):
        return None

    has_primary = candidate.competence_category_id is not None or any(
        e.is_primary for e in existing
    )
    if not overwrite and has_primary:
        return None

    # Clean slate: every remaining row here is AI-sourced (manual ruled out).
    if existing:
        await db.execute(
            CandidateCompetenceCategory.__table__.delete().where(
                CandidateCompetenceCategory.candidate_id == candidate.id
            )
        )

    secondary = [s for s in scores[1:] if s.score >= SECONDARY_MIN_SCORE][
        :MAX_SECONDARY
    ]

    db.add(
        CandidateCompetenceCategory(
            candidate_id=candidate.id,
            competence_category_id=top.cc_id,
            is_primary=True,
            confidence_score=_clamp_confidence(top.score),
            source=_source_for_score(top.score),
        )
    )
    written_secondary: list[str] = []
    for s in secondary:
        if s.cc_id == top.cc_id:
            continue
        db.add(
            CandidateCompetenceCategory(
                candidate_id=candidate.id,
                competence_category_id=s.cc_id,
                is_primary=False,
                confidence_score=_clamp_confidence(s.score),
                source=_source_for_score(s.score),
            )
        )
        written_secondary.append(s.slug)

    # Sync legacy single-value fields to the primary (list filter + badge read it).
    candidate.competence_category = top.slug
    candidate.competence_category_id = top.cc_id

    return {
        "primary": top.slug,
        "primary_score": top.score,
        "secondary": written_secondary,
    }


def _tally(by_primary: dict[str, int], slug: str) -> None:
    by_primary[slug] = by_primary.get(slug, 0) + 1


async def backfill_candidate_ccs(
    db: AsyncSession,
    *,
    limit: Optional[int] = None,
    only_missing: bool = True,
    dry_run: bool = False,
    progress: Optional[dict[str, Any]] = None,
    start_after_id: int = 0,
) -> dict[str, Any]:
    """Classify candidates into competence categories in bulk.

    ``only_missing=True`` (default) targets only candidates with no primary CC
    (``competence_category_id IS NULL``) — the safe migration path that never
    touches already-classified or manually-curated profiles. ``only_missing=
    False`` re-classifies **every** candidate (still skips manual rows); use it
    deliberately to refresh the whole corpus after a classifier change.

    ``start_after_id`` is a resume cursor: only candidates with ``id >`` this
    value are scanned. Low-signal candidates below the classification floor are
    *skipped* but stay NULL, so a plain restart would rescan that ever-growing
    convoy from id 0. The caller (admin keeper / CLI) tracks the ``last_id``
    watermark this function maintains in ``progress`` and re-kicks with it, so
    one pass over the id range completes even across container restarts.

    Commits per candidate so a long run is resumable and partial progress
    survives a container restart. Returns aggregate stats; ``progress`` (an
    in-memory dict, e.g. from the admin endpoint) is updated live if given.
    """
    conditions: list[str] = []
    params: dict[str, Any] = {}
    if only_missing:
        conditions.append("competence_category_id IS NULL")
    if start_after_id:
        conditions.append("id > :start_after_id")
        params["start_after_id"] = start_after_id
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    limit_clause = "LIMIT :limit" if limit is not None else ""
    if limit is not None:
        params["limit"] = limit

    rows = await db.execute(
        text(f"SELECT id FROM candidates {where} ORDER BY id {limit_clause}"),
        params,
    )
    ids = [r.id for r in rows]

    stats: dict[str, Any] = {
        "total": len(ids),
        "processed": 0,
        "assigned": 0,
        "skipped": 0,
        "errors": 0,
        "by_primary": {},
        "dry_run": dry_run,
        "start_after_id": start_after_id,
        "last_id": start_after_id,
    }
    if progress is not None:
        progress.update(stats)
    if not ids:
        return stats

    for cand_id in ids:
        candidate = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        if candidate is None:
            stats["processed"] += 1
            continue
        try:
            scores = await classify_candidate_to_cc(candidate, db)
            top = scores[0] if scores else None
            if top is None or top.score < PRIMARY_MIN_SCORE:
                stats["skipped"] += 1
            elif dry_run:
                stats["assigned"] += 1
                _tally(stats["by_primary"], top.slug)
            else:
                summary = await apply_candidate_cc_scores(
                    candidate, scores, db, overwrite=True
                )
                if summary is None:
                    # Manual-curated (or nothing to write) — leave untouched.
                    stats["skipped"] += 1
                else:
                    await db.commit()
                    stats["assigned"] += 1
                    _tally(stats["by_primary"], summary["primary"])
        except Exception as e:  # noqa: BLE001 — one bad row must not kill the run
            await db.rollback()
            stats["errors"] += 1
            logger.warning("[cc_backfill] candidate %s failed: %s", cand_id, e)
        stats["processed"] += 1
        stats["last_id"] = cand_id
        if progress is not None:
            progress.update(stats)
        if stats["processed"] % 50 == 0:
            logger.info(
                "[cc_backfill] %d/%d processed (assigned=%d skipped=%d errors=%d)",
                stats["processed"],
                stats["total"],
                stats["assigned"],
                stats["skipped"],
                stats["errors"],
            )

    logger.info(
        "[cc_backfill] done: %s %d/%d (skipped=%d errors=%d) by_primary=%s",
        "would assign" if dry_run else "assigned",
        stats["assigned"],
        stats["total"],
        stats["skipped"],
        stats["errors"],
        stats["by_primary"],
    )
    return stats
