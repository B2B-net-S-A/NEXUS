"""Exhaustive candidate evaluation with verifiable coverage and stable pages.

Retrieval top-K is not an input here: the source is the database population
snapshot. Transport/storage adapters can persist each batch and progress. A
failed batch is not an empty match set and never produces a complete ranking.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Sequence


@dataclass(frozen=True)
class CandidateSnapshot:
    candidate_id: int
    version: str


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id: int
    candidate_version: str
    eligible: bool
    fit_score: float | None
    measurement: Literal["measured", "unavailable", "missing_index", "stale"]
    evidence: dict = field(default_factory=dict)
    exclusion_reasons: tuple[str, ...] = ()

    def __post_init__(self):
        if self.fit_score is not None:
            if not math.isfinite(self.fit_score) or not 0 <= self.fit_score <= 100:
                raise ValueError("fit_score must be finite and in [0, 100]")
            if self.measurement != "measured":
                raise ValueError("Unmeasured candidates cannot have a fit score")


@dataclass
class FullScanResult:
    run_id: str
    population_size: int
    evaluated: list[CandidateEvaluation] = field(default_factory=list)
    failed_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def coverage_complete(self) -> bool:
        return not self.failed_ids and len(self.evaluated) == self.population_size

    @property
    def ranking_complete(self) -> bool:
        return self.coverage_complete and all(
            not row.eligible or row.measurement == "measured" for row in self.evaluated
        )

    def counts(self) -> dict:
        eligible = [r for r in self.evaluated if r.eligible]
        return {
            "population": self.population_size,
            "evaluated": len(self.evaluated),
            "excluded": sum(not r.eligible for r in self.evaluated),
            "eligible": len(eligible),
            "measured": sum(r.measurement == "measured" for r in eligible),
            "needs_verification": sum(r.measurement != "measured" for r in eligible),
            "failed": len(self.failed_ids),
            "coverage_complete": self.coverage_complete,
            "ranking_complete": self.ranking_complete,
        }

    def page(self, *, offset: int = 0, limit: int = 20, min_score: float = 0) -> dict:
        if offset < 0 or not 1 <= limit <= 100 or not 0 <= min_score <= 100:
            raise ValueError("Invalid page or threshold")
        # Unknown measurement is preserved for review regardless of threshold.
        rows = [
            r
            for r in self.evaluated
            if r.eligible and (r.fit_score is None or r.fit_score >= min_score)
        ]
        rows.sort(
            key=lambda r: (r.fit_score is None, -(r.fit_score or 0), r.candidate_id)
        )
        return {
            "run_id": self.run_id,
            "rows": rows[offset : offset + limit],
            "total_after_threshold": len(rows),
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "counts": self.counts(),
        }


EvaluateBatch = Callable[
    [Sequence[CandidateSnapshot]], Awaitable[Sequence[CandidateEvaluation]]
]
Progress = Callable[[FullScanResult], Awaitable[None]]


async def scan_population(
    population: Sequence[CandidateSnapshot],
    evaluate_batch: EvaluateBatch,
    *,
    batch_size: int = 256,
    run_id: str | None = None,
    on_progress: Progress | None = None,
) -> FullScanResult:
    """Visit every snapshot ID exactly once, even after a provider batch fails.

    Adapters must return an evaluation for every ID, including ineligible IDs.
    Source-version changes and missing records remain explicit failed coverage.
    A persistence callback failure propagates: an unpersisted run must not be
    announced as durably completed. Cancellation also propagates.
    """
    if batch_size < 1 or batch_size > 1000:
        raise ValueError("batch_size must be in [1, 1000]")
    ids = [row.candidate_id for row in population]
    if len(set(ids)) != len(ids):
        raise ValueError("Population snapshot contains duplicate candidate IDs")
    result = FullScanResult(run_id=run_id or uuid.uuid4().hex, population_size=len(ids))
    for start in range(0, len(population), batch_size):
        batch = population[start : start + batch_size]
        expected = {row.candidate_id: row.version for row in batch}
        try:
            rows = list(await evaluate_batch(batch))
            returned_ids = [r.candidate_id for r in rows]
            if (
                len(set(returned_ids)) != len(returned_ids)
                or set(returned_ids) - expected.keys()
            ):
                raise ValueError(
                    "Batch evaluator returned duplicate or foreign candidate IDs"
                )
            by_id = {row.candidate_id: row for row in rows}
            for cid, version in expected.items():
                row = by_id.get(cid)
                if row is None or row.candidate_version != version:
                    result.failed_ids.append(cid)
                    continue
                result.evaluated.append(row)
        except Exception as exc:
            # No candidate details or provider response body in run diagnostics.
            result.errors.append(type(exc).__name__)
            result.failed_ids.extend(expected)
        if on_progress is not None:
            await on_progress(result)
    return result


async def snapshot_candidate_population(db) -> list[CandidateSnapshot]:
    """Capture SQL IDs and versions in one statement, without an index/top-K gate.

    This internal function grants no access; the evaluator must apply access
    and eligibility rules before exposing any candidate to the requester.
    """
    from sqlalchemy import select
    from app.models.candidate import Candidate

    rows = await db.execute(
        select(Candidate.id, Candidate.updated_at).order_by(Candidate.id)
    )
    return [CandidateSnapshot(cid, str(version)) for cid, version in rows]


async def load_snapshot_batch(db, batch: Sequence[CandidateSnapshot]):
    """Deleted/changed records are omitted, making coverage explicitly incomplete."""
    from sqlalchemy import select
    from app.models.candidate import Candidate

    expected = {row.candidate_id: row.version for row in batch}
    if not expected:
        return {}
    rows = (
        (
            await db.execute(
                select(Candidate)
                .where(Candidate.id.in_(expected))
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return {row.id: row for row in rows if str(row.updated_at) == expected[row.id]}
