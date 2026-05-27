"""
Phase 3 endpoints:

- PUT  /api/pipeline-stages/{stage_def_id}/scorecard  — edit scorecard_schema
- GET  /api/pipeline-stages/{stage_def_id}/scorecard  — read scorecard_schema
- PATCH /api/pipeline/{candidate_stage_id}/scorecard  — save answers for a move
- GET  /api/pipeline/overview-sla                     — stages breaching sla_max_days
- GET  /api/candidates/{id}/pipelines                 — all pipelines (multi-job view)
- GET  /api/reports/funnel                            — conversion per stage per template
- GET  /api/reports/time-to-hire                      — median + p90 days-to-hire, per recruiter
- POST /api/jobs/embed-all                            — backfill nexus_jobs Qdrant collection
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, ManagerOrAdmin
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.pipeline_template import (
    PipelineStageDef,
    PipelineTemplate,
)
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.schemas.scorecard import ScorecardSchema, ScorecardSubmission

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Scorecards ───────────────────────────────────────────────────────────────


@router.get("/pipeline-stages/{stage_def_id}/scorecard")
async def get_stage_scorecard(
    stage_def_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Return the scorecard schema for one PipelineStageDef."""
    stage = await db.scalar(
        select(PipelineStageDef).where(PipelineStageDef.id == stage_def_id)
    )
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    return {
        "stage_def_id": stage.id,
        "stage_name": stage.name,
        "schema": stage.scorecard_schema or {"title": None, "questions": []},
    }


@router.put("/pipeline-stages/{stage_def_id}/scorecard")
async def set_stage_scorecard(
    stage_def_id: int,
    data: ScorecardSchema,
    current_user: ManagerOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Replace the scorecard schema for one PipelineStageDef."""
    stage = await db.scalar(
        select(PipelineStageDef).where(PipelineStageDef.id == stage_def_id)
    )
    if not stage:
        raise HTTPException(status_code=404, detail="Stage not found")
    stage.scorecard_schema = data.model_dump()
    await db.commit()
    return {"ok": True, "stage_def_id": stage.id}


@router.patch("/pipeline/{candidate_stage_id}/scorecard")
async def submit_scorecard_answers(
    candidate_stage_id: int,
    data: ScorecardSubmission,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Persist scorecard answers on a CandidateStage row."""
    stage = await db.scalar(
        select(CandidateStage).where(CandidateStage.id == candidate_stage_id)
    )
    if not stage:
        raise HTTPException(status_code=404, detail="CandidateStage not found")

    stage.scorecard_answers = {
        "answers": [a.model_dump() for a in data.answers],
        "overall_rating": data.overall_rating,
        "notes": data.notes,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "submitted_by": current_user.id,
    }
    if data.overall_rating is not None:
        stage.rating = data.overall_rating
    await db.commit()
    return {"ok": True, "candidate_stage_id": stage.id}


# ── SLA overview ─────────────────────────────────────────────────────────────


@router.get("/pipeline/overview-sla")
async def sla_alerts(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """List CandidateStage rows that exceeded PipelineStageDef.sla_max_days.

    Optimized 2026-05-27: dawniej pełen scan 158k rows + Python loop "latest
    per pair" — wisiało >15s. Teraz:
    1. Pre-fetch tylko PipelineStageDef z sla_max_days IS NOT NULL i NOT
       is_terminal (kilkanaście wpisów) — to definicje które MOGĄ breach
    2. SELECT candidate_stages tylko ze stage_def_id w tej puli
    3. DISTINCT ON w Postgres żeby dostać latest per pair w SQL zamiast
       Python defaultdict
    """
    sla_defs = (
        (
            await db.execute(
                select(PipelineStageDef).where(
                    PipelineStageDef.sla_max_days.isnot(None),
                    PipelineStageDef.is_terminal == False,  # noqa: E712
                )
            )
        )
        .scalars()
        .all()
    )
    if not sla_defs:
        return {"count": 0, "alerts": []}

    stage_defs: dict[int, PipelineStageDef] = {sd.id: sd for sd in sla_defs}
    sla_def_ids = list(stage_defs.keys())

    # DISTINCT ON dla "latest stage per (candidate, job)" — w SQL, nie
    # w Python. Filtrujemy tylko po sla_def_ids więc skanujemy
    # microscopic subset.
    latest_rows = (
        (
            await db.execute(
                select(CandidateStage)
                .where(CandidateStage.stage_def_id.in_(sla_def_ids))
                .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
                .order_by(
                    CandidateStage.candidate_id,
                    CandidateStage.job_id,
                    CandidateStage.moved_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )

    # Sprawdź czy najnowsza stage per pair NAPRAWDĘ należy do SLA-eligible
    # def — pair może mieć nowszą stage w terminal/no-SLA def (np. hired).
    candidate_pairs = [(s.candidate_id, s.job_id) for s in latest_rows]
    if not candidate_pairs:
        return {"count": 0, "alerts": []}

    actually_latest_rows = (
        (
            await db.execute(
                select(CandidateStage)
                .where(
                    CandidateStage.candidate_id.in_(
                        list({c for c, _ in candidate_pairs})
                    ),
                    CandidateStage.job_id.in_(
                        list({j for _, j in candidate_pairs})
                    ),
                )
                .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
                .order_by(
                    CandidateStage.candidate_id,
                    CandidateStage.job_id,
                    CandidateStage.moved_at.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    truly_latest: dict[tuple[int, int], CandidateStage] = {
        (s.candidate_id, s.job_id): s for s in actually_latest_rows
    }

    now = datetime.now(timezone.utc)
    breaches: list[dict] = []
    for s in latest_rows:
        # Skip jeśli kandydat ma już nowszą stage poza SLA-eligible def
        # (np. przeszedł do "hired" lub innej terminal).
        current = truly_latest.get((s.candidate_id, s.job_id))
        if current is None or current.id != s.id:
            continue
        sd = stage_defs.get(s.stage_def_id or 0)
        if not sd or not sd.sla_max_days:
            continue
        moved = s.moved_at
        if moved.tzinfo is None:
            moved = moved.replace(tzinfo=timezone.utc)
        days = (now - moved).days
        if days > sd.sla_max_days:
            breaches.append(
                {
                    "candidate_stage_id": s.id,
                    "candidate_id": s.candidate_id,
                    "job_id": s.job_id,
                    "stage_def_id": sd.id,
                    "stage_name": sd.name,
                    "days_in_stage": days,
                    "sla_max_days": sd.sla_max_days,
                    "overdue_by_days": days - sd.sla_max_days,
                }
            )
    breaches.sort(key=lambda x: -x["overdue_by_days"])
    return {"count": len(breaches), "alerts": breaches}


# ── Multi-pipeline view per candidate ────────────────────────────────────────


@router.get("/candidates/{candidate_id}/pipelines")
async def candidate_pipelines(
    candidate_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Return every pipeline the candidate is currently in, with latest stage
    info. Ideal for the "co z nim jest?" widget.
    """
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    rows = await db.execute(
        select(CandidateStage)
        .where(CandidateStage.candidate_id == candidate_id)
        .order_by(CandidateStage.job_id, CandidateStage.moved_at.desc())
    )
    stages = rows.scalars().all()

    # Latest stage per job_id
    latest: dict[int, CandidateStage] = {}
    for s in stages:
        if s.job_id not in latest:
            latest[s.job_id] = s

    # Prefetch Jobs + StageDefs
    job_ids = list(latest.keys())
    jobs_by_id: dict[int, Job] = {}
    if job_ids:
        jb = await db.execute(select(Job).where(Job.id.in_(job_ids)))
        jobs_by_id = {j.id: j for j in jb.scalars().all()}

    stage_def_ids = {s.stage_def_id for s in latest.values() if s.stage_def_id}
    stage_defs_by_id: dict[int, PipelineStageDef] = {}
    if stage_def_ids:
        sd = await db.execute(
            select(PipelineStageDef).where(PipelineStageDef.id.in_(stage_def_ids))
        )
        stage_defs_by_id = {x.id: x for x in sd.scalars().all()}

    pipelines: list[dict] = []
    now = datetime.now(timezone.utc)
    for s in latest.values():
        job = jobs_by_id.get(s.job_id)
        sd = stage_defs_by_id.get(s.stage_def_id or 0)
        moved = s.moved_at
        if moved.tzinfo is None:
            moved = moved.replace(tzinfo=timezone.utc)
        pipelines.append(
            {
                "candidate_stage_id": s.id,
                "job_id": s.job_id,
                "job_title": job.title if job else None,
                "client_id": job.client_id if job else None,
                "stage_name": sd.name if sd else (s.stage.value if s.stage else None),
                "stage_category": sd.category.value if sd else None,
                "is_terminal": sd.is_terminal if sd else False,
                "moved_at": s.moved_at.isoformat() if s.moved_at else None,
                "days_in_stage": max(0, (now - moved).days),
                "rating": s.rating,
                "has_scorecard": bool(s.scorecard_answers),
            }
        )
    pipelines.sort(key=lambda p: (p["is_terminal"], p["job_id"]))

    return {
        "candidate_id": candidate_id,
        "candidate_name": f"{candidate.name} {candidate.lastname}",
        "count": len(pipelines),
        "pipelines": pipelines,
    }


# ── Reports ──────────────────────────────────────────────────────────────────


@router.get("/reports/funnel")
async def funnel_report(
    current_user: CurrentUser,
    template_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Conversion per stage — count of distinct candidates who ever reached each stage."""
    q = select(PipelineStageDef).order_by(PipelineStageDef.order)
    if template_id:
        q = q.where(PipelineStageDef.template_id == template_id)
    else:
        default_id = await db.scalar(
            select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
        )
        if default_id:
            q = q.where(PipelineStageDef.template_id == default_id)
    stage_defs = (await db.execute(q)).scalars().all()

    # Denominator: liczba unikalnych kandydatów którzy *kiedykolwiek* byli w
    # tym pipeline (suma distinct candidate_id across all stage_defs w template).
    # Stary algorytm (count/prev_count) dawał wartości 1700%+ gdy etap miał
    # więcej kandydatów niż bezpośrednio poprzedni etap (Preparation Call
    # opcjonalna z count=1, Screening z count=17 → 1700%). Pierwszy fix
    # użył count z entry stage — ale to wciąż >100% bo kandydaci wpadają na
    # różne stagey bez przechodzenia przez "Nowi/Analiza CV" (referrals,
    # sourcing pipeline). Total distinct gwarantuje że każdy stage ≤100%.
    stage_def_id_set = {sd.id for sd in stage_defs}
    total_unique = 0
    if stage_def_id_set:
        total_unique = (
            await db.scalar(
                select(func.count(func.distinct(CandidateStage.candidate_id))).where(
                    CandidateStage.stage_def_id.in_(stage_def_id_set)
                )
            )
            or 0
        )

    funnel: list[dict] = []
    prev_count: int | None = None
    for sd in stage_defs:
        count = await db.scalar(
            select(func.count(func.distinct(CandidateStage.candidate_id))).where(
                CandidateStage.stage_def_id == sd.id
            )
        )
        count = count or 0
        # Overall conversion: % unikalnych kandydatów którzy ever weszli do pipeline.
        conversion_pct = (
            round(count / total_unique * 100.0, 1) if total_unique else None
        )
        # Step conversion: % z poprzedniego etapu, capped 100% (gdy etap był
        # opcjonalny, kandydaci omijają go i suma current > prev).
        step_pct = (
            round(min(count / prev_count * 100.0, 100.0), 1) if prev_count else None
        )
        funnel.append(
            {
                "stage_def_id": sd.id,
                "stage_name": sd.name,
                "order": sd.order,
                "category": sd.category.value,
                "is_terminal": sd.is_terminal,
                "count": count,
                "conversion_pct": conversion_pct,
                "step_conversion_pct": step_pct,
            }
        )
        if not sd.is_terminal:
            prev_count = count if count > 0 else prev_count
    return {"template_id": template_id, "funnel": funnel}


@router.get("/reports/time-to-hire")
async def time_to_hire(
    current_user: CurrentUser,
    days_lookback: int = Query(180, ge=7, le=720),
    db: AsyncSession = Depends(get_db),
):
    """
    Per-recruiter days-to-hire stats based on (first stage moved_at → hired stage moved_at).
    """
    since = datetime.now(timezone.utc) - timedelta(days=days_lookback)

    # All stage rows in window
    rows = (
        (
            await db.execute(
                select(CandidateStage)
                .where(CandidateStage.moved_at >= since)
                .order_by(
                    CandidateStage.candidate_id,
                    CandidateStage.job_id,
                    CandidateStage.moved_at,
                )
            )
        )
        .scalars()
        .all()
    )

    # Group by (candidate, job)
    groups: dict[tuple[int, int], list[CandidateStage]] = defaultdict(list)
    for s in rows:
        groups[(s.candidate_id, s.job_id)].append(s)

    per_recruiter: dict[int, list[int]] = defaultdict(list)  # days_to_hire list
    placements = 0
    for (cid, jid), items in groups.items():
        if not items:
            continue
        start = items[0].moved_at
        hired = next(
            (x for x in items if x.stage == PipelineStage.hired),
            None,
        )
        if not hired:
            continue
        placements += 1
        days = max(0, (hired.moved_at - start).days)
        owner = hired.moved_by or items[0].moved_by or 0
        per_recruiter[owner].append(days)

    # Collect recruiter names
    recruiter_ids = [r for r in per_recruiter if r > 0]
    names: dict[int, str] = {}
    if recruiter_ids:
        urows = await db.execute(select(User).where(User.id.in_(recruiter_ids)))
        names = {u.id: u.name for u in urows.scalars().all()}

    def _median(xs: list[int]) -> Optional[float]:
        if not xs:
            return None
        s = sorted(xs)
        mid = len(s) // 2
        return float(s[mid]) if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0

    def _p90(xs: list[int]) -> Optional[int]:
        if not xs:
            return None
        s = sorted(xs)
        idx = min(len(s) - 1, int(0.9 * len(s)))
        return s[idx]

    results = [
        {
            "recruiter_id": rid,
            "name": names.get(rid, "Nieprzypisany"),
            "placements": len(days_list),
            "median_days": _median(days_list),
            "p90_days": _p90(days_list),
        }
        for rid, days_list in sorted(per_recruiter.items(), key=lambda kv: -len(kv[1]))
    ]

    return {
        "since": since.isoformat(),
        "total_placements": placements,
        "by_recruiter": results,
    }


# ── Batch backfill: embed every job that lacks embedding_id ─────────────────


@router.post("/jobs/embed-all")
async def embed_all_jobs(
    current_user: ManagerOrAdmin,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """
    One-shot embedder for jobs that have no embedding_id. Used after Phase 2
    deploy to backfill the nexus_jobs Qdrant collection.
    """
    from app.services.embedding_service import embed_job

    rows = await db.execute(
        select(Job.id).where(Job.embedding_id.is_(None)).limit(limit)
    )
    job_ids = [jid for (jid,) in rows.all()]

    embedded = 0
    failed = 0
    for jid in job_ids:
        try:
            ok = await embed_job(jid, db)
            if ok:
                embedded += 1
            else:
                failed += 1
        except Exception as e:  # pragma: no cover
            logger.warning(f"[embed-all] job {jid} failed: {e}")
            failed += 1

    return {
        "requested": len(job_ids),
        "embedded": embedded,
        "failed": failed,
    }
