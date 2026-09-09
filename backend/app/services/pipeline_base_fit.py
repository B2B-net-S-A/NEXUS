"""Pipeline cards use the full-search evaluator, with process data separate."""

from sqlalchemy import select

from app.models.candidate import Candidate
from app.models.recruitment_pipeline import CandidateStage
from app.services.candidate_search_worker import evaluate_batch
from app.services.full_candidate_scan import CandidateSnapshot, scan_population
from app.services.full_search_measurement import request_vector
from app.services.request_matching_context import build_request_context
from app.services.search_telemetry import SearchTelemetry, stage


async def pipeline_base_fit(db, job, profile):
    job_id = job.id
    context = build_request_context(job, profile)
    rows = await db.execute(
        select(Candidate.id, Candidate.updated_at)
        .where(
            Candidate.id.in_(
                select(CandidateStage.candidate_id).where(
                    CandidateStage.job_id == job.id
                )
            )
        )
        .order_by(Candidate.id)
    )
    population = [CandidateSnapshot(cid, str(version)) for cid, version in rows]
    telemetry = SearchTelemetry()
    telemetry.begin_attempt()
    with telemetry.activate():
        vector = None
        if population:
            with stage("query_embedding") as outcome:
                try:
                    vector = await request_vector(context.query_text)
                    outcome["failed"] = vector is None
                except Exception:
                    outcome["failed"] = True

        async def evaluate(batch):
            try:
                with stage("batch"):
                    return await evaluate_batch(db, context, batch, vector)
            except Exception:
                await db.rollback()
                raise

        result = await scan_population(population, evaluate, batch_size=256)
    return {
        "job_id": job_id,
        "profile_id": profile.id,
        "request_fingerprint": context.fingerprint,
        "versions": context.versions,
        "pipeline_candidate_ids": [item.candidate_id for item in population],
        "scores": {
            str(item.candidate_id): item.fit_score
            for item in result.evaluated
            if item.eligible and item.fit_score is not None
        },
        "measurements": {
            str(item.candidate_id): item.measurement for item in result.evaluated
        },
        "counts": result.counts(),
        "metrics": telemetry.snapshot(),
    }
