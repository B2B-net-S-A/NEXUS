"""One base-fit calculation for every candidate/request presentation.

Retrieval scores select candidates only. They are never substitutes for the
exact, provenance-checked semantic measurement used in a fit score.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.full_search_measurement import measure_candidates, request_vector
from app.services.request_matching_context import RequestMatchingContext
from app.services.search_telemetry import stage

if TYPE_CHECKING:
    from app.services.scoring_service import ScoreBreakdown

# Scoring a base fit never awaits real I/O, so a 1000-candidate pool would
# otherwise hold the event loop for the whole loop in the web process.
YIELD_EVERY = 32


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


def display_score(fit_score: float | None) -> int | None:
    """Integer badge value for a fit score, rounded like the UI's ``Math.round``.

    Python's ``round`` rounds half to even (72.5 -> 72) while the front end
    rounds half up (72.5 -> 73); a screen that receives an int from the API and
    one that rounds the float itself must not disagree on the same pair.
    ``None`` (not measured) stays ``None`` — it is never shown as 0.
    """
    if fit_score is None:
        return None
    return int(math.floor(min(max(float(fit_score), 0.0), 100.0) + 0.5))


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
    from app.services.requirement_verification import load_verified_requirements

    await load_verified_requirements(db, context.as_job(), candidates)
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
        for index, candidate in enumerate(batch):
            if index and index % YIELD_EVERY == 0:
                await asyncio.sleep(0)
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
