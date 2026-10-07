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


def uses_prior_screening(context: RequestMatchingContext) -> bool:
    """Warstwa wcześniejszych rozmów — decyzja zamrożona w żądaniu, nie flaga
    z chwili oceny: przegląd zaczęty przy OFF dokończy się bez niej."""
    from app.services.prior_screening import VERSION

    return context.versions.get("prior_screening") == VERSION


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
            prior_screening=uses_prior_screening(context),
        )
    return CanonicalFit(breakdown, measurement.status)


async def _attach_missing_evidence(db, job, candidates) -> None:
    """Dowód z CV i notatek przed oceną (30.09.2026) — ocena umiejętności
    czyta go tak samo jak bramka. Kandydaci z dowodem dołączonym już przez
    bramkę tej rekrutacji nie są czytani drugi raz."""
    if db is None:
        return
    from app.services.dealbreaker_filters import dealbreaker_inputs_for_job
    from app.services.must_text_evidence import attach_gate_evidence, evidence_for

    labels = dealbreaker_inputs_for_job(job).gate_evidence_labels
    missing = [c for c in candidates if evidence_for(c, labels) is None]
    if missing:
        await attach_gate_evidence(db, missing, labels)


async def score_candidates(db, context: RequestMatchingContext, candidates):
    """Score supplied identities against the same full request as Radar/C2.

    Does not grant visibility or claim exhaustive retrieval. Callers own their
    population, eligibility and pagination. No legacy score cache is read/written.
    """
    if not candidates:
        return []
    from app.services.requirement_verification import load_verified_requirements

    job = context.as_job()
    await load_verified_requirements(db, job, candidates)
    await _attach_missing_evidence(db, job, candidates)
    if uses_prior_screening(context):
        from app.services.prior_screening import attach_prior_screening

        await attach_prior_screening(db, job, candidates)
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
