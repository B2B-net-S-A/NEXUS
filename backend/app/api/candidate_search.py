"""Shared durable full-search transport for Radar and recruitment requests."""

from copy import deepcopy
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import require_candidate_read
from app.api.deps import CurrentUser, get_db
from app.api.section_access import require_section_access_any_read
from app.api.talent_radar import TalentRadarSearchRequest
from app.models.candidate_search_run import CandidateSearchRun
from app.models.client import Client
from app.models.job import Job
from app.models.user import User
from app.services import candidate_search_store as store
from app.services.search_eligibility_freshness import eligibility_fingerprint
from app.services.request_matching_context import (
    RequestMatchingContext,
    build_request_context,
)
from app.services.scoring_service import job_skill_requirements, resolve_active_profile
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)
from app.services.talent_radar_search import (
    RadarQuery,
    build_ephemeral_job,
    shape_radar_candidate,
)

router = APIRouter(
    dependencies=[
        Depends(
            require_section_access_any_read(
                ProductSection.sourcing,
                ProductSection.pipeline,
            )
        )
    ]
)


@router.get("/candidate-search/jobs/{job_id}/requirements")
async def search_requirements(
    job_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    from app.services.requirement_contract import requirements_for_job

    _search_access(user)
    job = await _authorized_job(db, user, job_id)
    return requirements_for_job(job)


def _search_access(user):
    if (
        max(
            section_access_for_user(user, ProductSection.sourcing),
            section_access_for_user(user, ProductSection.pipeline),
        )
        < SectionAccess.read
    ):
        raise HTTPException(403, "Brak dostępu do wyszukiwania kandydatów")


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

    if section_access_for_user(user, ProductSection.pipeline) < SectionAccess.read:
        raise HTTPException(403, "Brak dostępu do rekrutacji")
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "Rekrutacja nie istnieje")
    _assert_delivery_lead_job_visible(job, await _delivery_lead_job_pairs(user, db))
    return job


@router.post("/candidate-search/runs", status_code=202)
async def start_search(
    payload: StartSearchRequest,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    _search_access(user)
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
        version_trace={
            **context.versions,
            "eligibility_fingerprint": await eligibility_fingerprint(db, job=job),
        },
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
    user: CurrentUser,
    include_candidate_details: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    min_score: float = Query(0, ge=0, le=100),
    skill: str = "",
    rate: Literal["all", "in", "over", "unknown"] = "all",
    stage: Literal["all", "in", "out"] = "all",
    location: str = "",
    db: AsyncSession = Depends(get_db),
):
    _search_access(user)
    if include_candidate_details:
        await require_candidate_read(user)
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
            "metrics": run.metrics or {},
            "results": [],
            "versions": run.version_trace,
        }
    data_changed = await store.population_changed(db, run.id)
    current_eligibility = await eligibility_fingerprint(db, job=job)
    data_changed = data_changed or current_eligibility != (run.version_trace or {}).get(
        "eligibility_fingerprint"
    )
    from app.services.full_search_filters import ResultFilters

    if stage != "all" and run.job_id is None:
        raise HTTPException(422, "Filtr procesu wymaga zapisanej rekrutacji")
    rows, total = await store.result_page(
        db,
        run.id,
        offset=offset,
        limit=limit,
        min_score=min_score,
        filters=ResultFilters(
            skill=skill, rate=rate, stage=stage, location=location, job_id=run.job_id
        ),
    )
    from app.models.candidate import Candidate

    current = {
        candidate.id: candidate
        for candidate in (
            await db.execute(
                select(Candidate).where(
                    Candidate.id.in_([r.candidate_id for r in rows])
                )
            )
        )
        .scalars()
        .all()
    }
    from app.services.pipeline_eligibility import evaluate_candidates_for_job
    from app.services.candidate_job_eligibility import Visibility

    decisions = await evaluate_candidates_for_job(
        db, job=job, candidate_ids=list(current), now=datetime.now(timezone.utc)
    )
    from app.api.matching import _eligibility_annotation

    results = []
    for row in rows:
        decision = decisions.get(row.candidate_id)
        if (
            row.candidate_id not in current
            or decision is None
            or decision.visibility == Visibility.hidden
        ):
            data_changed = True
            continue
        annotation = _eligibility_annotation(decision)
        if annotation != (row.evidence or {}).get("eligibility"):
            data_changed = True
        row_changed = str(current[row.candidate_id].updated_at) != row.candidate_version
        data_changed = data_changed or row_changed
        breakdown = deepcopy((row.evidence or {}).get("breakdown") or {})
        requirements = deepcopy((row.evidence or {}).get("requirements", []))
        if row_changed:
            # Snapshot facts must not appear as current positive evidence.
            breakdown = {}
            for requirement in requirements:
                requirement.update(
                    status="unknown",
                    matched=[],
                    stale=True,
                    evidence_basis="no_evidence",
                    verified_at=None,
                    usage_context=None,
                    candidate_evidence=None,
                    verification_id=None,
                )
        if not include_candidate_details:
            for requirement in requirements:
                requirement.pop("candidate_evidence", None)
                requirement.pop("usage_context", None)
                requirement.pop("verification_id", None)
        fit_score = None if row_changed else row.fit_score
        breakdown["total"] = fit_score
        # Both entrances share the same conservative financial redaction.
        breakdown["salary"] = {
            "points": None,
            "max": None,
            "reason": None,
            "status": "redacted",
        }
        details = None
        if include_candidate_details:
            from app.api.matching import _build_match_info
            from app.services.dealbreaker_filters import dealbreaker_inputs_for_job

            labels = job_skill_requirements(context.as_job())
            details = _build_match_info(
                current[row.candidate_id],
                labels["must"],
                labels["nice"],
                score=(fit_score or 0) / 100,
                inputs=dealbreaker_inputs_for_job(context.as_job()),
            )
            details["match_score"] = fit_score / 100 if fit_score is not None else None
            details["eligibility"] = annotation
            details["breakdown"] = breakdown
            details["total_score"] = fit_score
            for level, matched_key, unknown_key in (
                ("must", "matching_skills", "gaps"),
                ("nice", "nice_matching", "nice_gaps"),
            ):
                details[matched_key] = [
                    " lub ".join(r["any_of"])
                    for r in requirements
                    if r["level"] == level and r["status"] == "met"
                ]
                details[unknown_key] = [
                    " lub ".join(r["any_of"])
                    for r in requirements
                    if r["level"] == level and r["status"] != "met"
                ]
            # Missing evidence is a review item; the run's explicit policy owns exclusion.
            details["missing_must"] = []
        results.append(
            {
                "match": details,
                "candidate": shape_radar_candidate(current[row.candidate_id]),
                "fit_score": fit_score,
                "measurement": "stale" if row_changed else row.measurement,
                "breakdown": breakdown,
                "requirements": requirements,
                "eligibility": annotation,
            }
        )
    from app.services.dealbreaker_filters import resolve_job_budget_hourly

    return {
        "run_id": run.id,
        "state": run.state,
        "counts": counts,
        "metrics": run.metrics or {},
        "results": results,
        "budget_hourly": resolve_job_budget_hourly(job),
        "total_after_threshold": total,
        "next_offset": offset + limit if offset + limit < total else None,
        "versions": run.version_trace,
        "request_fingerprint": run.request_fingerprint,
        "brief_status": context.brief_status,
        "coverage_complete": counts["failed"] == 0,
        "ranking_complete": run.state == "complete" and not data_changed,
        "data_changed": data_changed,
        "criteria": job_skill_requirements(context.as_job()),
    }
