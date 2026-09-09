"""Durable exhaustive search execution shared by saved and ad-hoc requests."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

from app.core.database import AsyncSessionLocal
from app.models.candidate_search_run import CandidateSearchRun
from app.services import candidate_search_store as store
from app.services.full_candidate_scan import CandidateEvaluation, load_snapshot_batch
from app.services.full_search_measurement import measure_candidates, request_vector
from app.services.request_matching_context import RequestMatchingContext
from app.services.search_telemetry import SearchTelemetry, stage


async def evaluate_batch(db, request: RequestMatchingContext, batch, vector):
    # Reuse the established visibility policy, including visible assignment
    # blocks and the invariant that global blacklist remains hidden.
    from app.api.matching import _gate_and_dealbreakers
    from app.services.dealbreaker_filters import (
        dealbreaker_inputs_for_job,
        rate_fit_status,
    )
    from app.services.location_utils import location_tokens
    from app.services.requirement_contract import (
        requirements_for_job,
        evaluate_requirements,
    )
    from app.services.canonical_fit import score_pair

    with stage("sql_load"):
        candidates = await load_snapshot_batch(db, batch)
    target = request.as_job()
    criteria = requirements_for_job(target)
    inputs = dealbreaker_inputs_for_job(target)
    # Missing proof is reviewable by default. Only an explicit saved policy
    # permits exclusion on absent skill evidence; other hard gates still apply.
    if criteria.missing_evidence_policy != "exclude":
        inputs = replace(inputs, must_skills=())
    with stage("eligibility"):
        kept, annotations, _, _, _ = await _gate_and_dealbreakers(
            db,
            job=target,
            ordered=list(candidates.values()),
            now=datetime.now(timezone.utc),
            inputs=inputs,
        )
    visible = {candidate.id for candidate in kept}
    with stage("retrieval") as outcome:
        measurements = await measure_candidates(vector, kept)
        outcome["failed"] = any(
            m.status == "unavailable" for m in measurements.values()
        )
    versions = {item.candidate_id: item.version for item in batch}
    results = []
    for cid, candidate in candidates.items():
        if cid not in visible:
            results.append(
                CandidateEvaluation(
                    cid,
                    versions[cid],
                    False,
                    None,
                    "unavailable",
                    exclusion_reasons=("eligibility_or_filter",),
                )
            )
            continue
        measurement = measurements[cid]
        fit = await score_pair(db, request, candidate, measurement)
        breakdown = fit.breakdown
        requirements = evaluate_requirements(criteria, candidate)
        results.append(
            CandidateEvaluation(
                cid,
                versions[cid],
                True,
                fit.fit_score,
                measurement.status,
                evidence={
                    "breakdown": breakdown.as_dict(),
                    "requirements": requirements,
                    "filters": {
                        "skills": [
                            " lub ".join(r["any_of"]).lower()
                            for r in requirements
                            if r["status"] == "met"
                        ],
                        "rate": rate_fit_status(candidate, inputs),
                        "locations": sorted(location_tokens(candidate.location)),
                    },
                    "eligibility": annotations.get(cid),
                    "brief_status": request.brief_status,
                },
            )
        )
    return results


async def execute_run(run_id: str):
    """Claim or resume pending IDs; committed batches survive process restarts.

    A scheduler/API trigger can safely call this again after lease expiry.
    It cannot race an active worker, or overwrite a replacement worker's rows.
    """
    async with AsyncSessionLocal() as db:
        token = await store.claim_run(db, run_id, lease_seconds=300)
        await db.commit()
        if token is None:
            return
        run = await db.get(CandidateSearchRun, run_id)
        request = RequestMatchingContext(**run.request_context)
        telemetry = SearchTelemetry(run.metrics)
        telemetry.begin_attempt()
        await store.save_metrics(db, run_id, token, telemetry.snapshot())
        await db.commit()
    with telemetry.activate(), stage("query_embedding") as outcome:
        try:
            vector = await request_vector(request.query_text)
            outcome["failed"] = vector is None
        except Exception:
            # Account for the population as unknown instead of retrying a
            # permanently invalid query forever at each lease expiry.
            outcome["failed"] = True
            vector = None
    async with AsyncSessionLocal() as db:
        await store.save_metrics(db, run_id, token, telemetry.snapshot())
        await db.commit()
    while True:
        async with AsyncSessionLocal() as db:
            batch = await store.pending_batch(db, run_id)
            if not batch:
                await store.finish_run(db, run_id, token)
                await db.commit()
                return
            error_code = None
            try:
                with telemetry.activate(), stage("batch"):
                    evaluations = await evaluate_batch(db, request, batch, vector)
            except Exception as exc:
                # Do not persist provider text or candidate data in errors.
                await db.rollback()
                evaluations = []
                error_code = type(exc).__name__
            await store.save_batch(
                db,
                run_id,
                token,
                batch,
                evaluations,
                error_code=error_code,
                metrics=telemetry.snapshot(),
            )
            await db.commit()
        await asyncio.sleep(0)  # yield between bounded CPU/SQL batches
