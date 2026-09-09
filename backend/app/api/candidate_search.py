"""Shared durable full-search transport for Radar and recruitment requests."""

from copy import deepcopy
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateSearchAccess
from app.api.deps import get_db
from app.api.talent_radar import TalentRadarSearchRequest
from app.models.candidate_search_run import CandidateSearchRun
from app.models.client import Client
from app.models.job import Job
from app.models.user import User
from app.services import candidate_search_store as store
from app.services.full_candidate_scan import CandidateSnapshot, load_snapshot_batch
from app.services.request_matching_context import (
    RequestMatchingContext,
    build_request_context,
)
from app.services.scoring_service import resolve_active_profile
from app.services.talent_radar_search import (
    RadarQuery,
    build_ephemeral_job,
    shape_radar_candidate,
)

router = APIRouter()


class StartSearchRequest(BaseModel):
    job_id: int | None = Field(default=None, gt=0)
    radar: TalentRadarSearchRequest | None = None

    @model_validator(mode="after")
    def one_request(self):
        if (self.job_id is None) == (self.radar is None):
            raise ValueError("Provide either job_id or radar request")
        return self


async def _authorized_job(db, user, job_id):
    from app.api.jobs import _assert_delivery_lead_job_visible, _delivery_lead_job_pairs

    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Rekrutacja nie istnieje")
    _assert_delivery_lead_job_visible(job, await _delivery_lead_job_pairs(user, db))
    return job


@router.post("/candidate-search/runs", status_code=202)
async def start_search(
    payload: StartSearchRequest,
    user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
):
    if payload.job_id is not None:
        job = await _authorized_job(db, user, payload.job_id)
    else:
        values = payload.radar.model_dump()
        job = build_ephemeral_job(RadarQuery(**values))
        if not job.description and not job.champion_profile:
            raise HTTPException(422, "Podaj request lub profil Championa")
    if not await db.get(Client, job.client_id):
        raise HTTPException(404, "Klient nie istnieje")
    profile = await resolve_active_profile(db, user_id=user.id, client_id=job.client_id)
    context = build_request_context(job, profile)
    # Serialize each actor's starts: two concurrent requests cannot bypass the
    # bounded number of active scans. This only locks a short start transaction.
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    active = await db.scalar(
        select(func.count())
        .select_from(CandidateSearchRun)
        .where(
            CandidateSearchRun.created_by == user.id,
            CandidateSearchRun.state.in_(["queued", "running"]),
        )
    )
    if active >= 2:
        raise HTTPException(
            409, "Dwa wyszukiwania już trwają. Poczekaj na ich zakończenie."
        )
    run = await store.create_run(
        db,
        actor_id=user.id,
        client_id=job.client_id,
        job_id=payload.job_id,
        request_fingerprint=context.fingerprint,
        request_context=context.as_dict(),
        version_trace=context.versions,
    )
    await db.commit()
    return {
        "run_id": run.id,
        "state": run.state,
        "population": run.population_size,
        "brief_status": context.brief_status,
        "versions": context.versions,
    }


@router.get("/candidate-search/runs/{run_id}")
async def search_results(
    run_id: str,
    user: CandidateSearchAccess,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100),
    db: AsyncSession = Depends(get_db),
):
    run = await store.owned_run(db, run_id, user.id)
    if run is None:
        raise HTTPException(404, "Wyszukiwanie nie istnieje")
    context = RequestMatchingContext(**run.request_context)
    job = (
        await _authorized_job(db, user, run.job_id) if run.job_id else context.as_job()
    )
    # A deleted saved job must not silently become an ad-hoc request.
    if context.job_data.get("id") is not None and run.job_id is None:
        raise HTTPException(409, "Rekrutacja została usunięta")
    profile = await resolve_active_profile(db, user_id=user.id, client_id=run.client_id)
    if build_request_context(job, profile).fingerprint != context.fingerprint:
        raise HTTPException(
            409,
            "Request lub profil punktacji zmienił się. Uruchom wyszukiwanie ponownie.",
        )
    counts = await store.run_counts(db, run.id)
    # Stable pages are exposed only after every snapshot ID is accounted for.
    if run.state not in {"complete", "partial"}:
        return {
            "run_id": run.id,
            "state": run.state,
            "counts": counts,
            "results": [],
            "versions": run.version_trace,
        }
    if await store.population_changed(db, run.id):
        raise HTTPException(
            409, "Baza kandydatów zmieniła się. Uruchom wyszukiwanie ponownie."
        )
    rows, total = await store.result_page(
        db, run.id, offset=offset, limit=limit, min_score=min_score
    )
    current = await load_snapshot_batch(
        db, [CandidateSnapshot(r.candidate_id, r.candidate_version) for r in rows]
    )
    if len(current) != len(rows):
        raise HTTPException(
            409, "Dane kandydatów zmieniły się. Uruchom wyszukiwanie ponownie."
        )
    from app.services.pipeline_eligibility import evaluate_candidates_for_job
    from app.services.candidate_job_eligibility import Visibility

    decisions = await evaluate_candidates_for_job(
        db, job=job, candidate_ids=list(current), now=datetime.now(timezone.utc)
    )
    results = []
    for row in rows:
        decision = decisions.get(row.candidate_id)
        if decision is None or decision.visibility == Visibility.hidden:
            raise HTTPException(
                409,
                "Dopuszczalność kandydatów zmieniła się. Uruchom wyszukiwanie ponownie.",
            )
        breakdown = deepcopy((row.evidence or {}).get("breakdown") or {})
        breakdown["total"] = row.fit_score
        # Both entrances share the same conservative financial redaction.
        breakdown["salary"] = {
            "points": None,
            "max": None,
            "reason": None,
            "status": "redacted",
        }
        from app.api.matching import _eligibility_annotation

        results.append(
            {
                "candidate": shape_radar_candidate(current[row.candidate_id]),
                "fit_score": row.fit_score,
                "measurement": row.measurement,
                "breakdown": breakdown,
                "requirements": (row.evidence or {}).get("requirements", []),
                "eligibility": _eligibility_annotation(decision),
            }
        )
    return {
        "run_id": run.id,
        "state": run.state,
        "counts": counts,
        "results": results,
        "total_after_threshold": total,
        "next_offset": offset + limit if offset + limit < total else None,
        "versions": run.version_trace,
        "request_fingerprint": run.request_fingerprint,
        "brief_status": context.brief_status,
        "coverage_complete": counts["failed"] == 0,
        "ranking_complete": run.state == "complete",
    }
