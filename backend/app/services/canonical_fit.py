"""One base-fit calculation for every candidate/request presentation.

Retrieval scores select candidates only. They are never substitutes for the
exact, provenance-checked semantic measurement used in a fit score.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.full_search_measurement import measure_candidates, request_vector
from app.services.request_matching_context import RequestMatchingContext
from app.services.search_telemetry import stage

if TYPE_CHECKING:
    from app.services.scoring_service import ScoreBreakdown


@dataclass
class CanonicalFit:
    breakdown: ScoreBreakdown
    measurement: str

    @property
    def fit_score(self):
        return self.breakdown.total if self.measurement == "measured" else None

    def as_dict(self):
        return {
            **self.breakdown.as_dict(),
            "total": self.fit_score,
            "measurement": self.measurement,
        }


async def score_pair(db, context: RequestMatchingContext, candidate, measurement):
    from app.services.scoring_service import score_candidate_job

    with stage("scoring"):
        breakdown = await score_candidate_job(
            candidate,
            context.as_job(),
            db,
            semantic_similarity=measurement.score,
            semantic_unavailable=measurement.status != "measured",
            profile=context.profile(),
            base_fit=True,
        )
    return CanonicalFit(breakdown, measurement.status)


async def score_candidates(db, context: RequestMatchingContext, candidates):
    """Score supplied identities against the same full request as Radar/C2.

    Does not grant visibility or claim exhaustive retrieval. Callers own their
    population, eligibility and pagination. No legacy score cache is read/written.
    """
    if not candidates:
        return []
    with stage("query_embedding") as outcome:
        try:
            vector = await request_vector(context.query_text)
            outcome["failed"] = vector is None
        except Exception:
            vector = None
            outcome["failed"] = True
    results = []
    for start in range(0, len(candidates), 256):
        batch = candidates[start : start + 256]
        with stage("retrieval") as outcome:
            measurements = await measure_candidates(vector, batch)
            outcome["failed"] = any(
                m.status == "unavailable" for m in measurements.values()
            )
        for candidate in batch:
            results.append(
                await score_pair(db, context, candidate, measurements[candidate.id])
            )
    results.sort(
        key=lambda item: (
            item.fit_score is None,
            -(item.fit_score or 0),
            item.breakdown.candidate_id,
        )
    )
    return results
