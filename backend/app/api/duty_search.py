"""„Kto już to robił” — API wyszukiwania po celu projektu i obowiązkach.

Reguła: ``docs/claude/kandydaci-wyszukiwanie/kto-juz-to-robil-wyszukiwanie-po-celu.md``.

- ``POST /duty-search/runs`` — z rekrutacji (``job_id``: obowiązki z Championa)
  albo z „Z requestu” (``client_id`` + opis celu). Przebieg liczy się w tle.
- ``GET /duty-search/runs/{id}`` — stan i wynik (autor albo osoba z dostępem
  do rekrutacji przebiegu).
- ``GET /jobs/{job_id}/duty-search/latest`` — najnowszy przebieg rekrutacji.
- ``PUT /duty-search/runs/{id}/results/{candidate_id}/feedback`` — „Trafne?”.

Bramka sekcji jak ``candidate_search`` (sourcing albo pipeline, co najmniej
odczyt). Zapora: ``DUTY_SEARCH_DAILY_LIMIT`` (10) przebiegów dziennie na osobę
i najwyżej dwa naraz. Bez ``from __future__ import annotations`` (slowapi #579).
"""

import uuid
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import NOT_READ_ONLY
from app.api.candidate_search import _authorized_job, _search_access
from app.api.deps import CurrentUser, get_db
from app.api.section_access import require_section_access_any_read
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.duty_search_run import DutySearchResult, DutySearchRun
from app.models.user import User
from app.services import duty_search
from app.services.section_permissions import ProductSection

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


class StartDutySearch(BaseModel):
    job_id: Optional[int] = Field(default=None, gt=0)
    client_id: Optional[int] = Field(default=None, gt=0)
    title: Optional[str] = Field(default=None, max_length=300)
    goal: Optional[str] = Field(default=None, max_length=duty_search.GOAL_MAX_CHARS)


class FeedbackBody(BaseModel):
    vote: Optional[Literal["up", "down"]] = None


def _duties_of(job) -> str:
    from app.services import champion_view

    return str(
        champion_view.project(job.champion_profile).get("responsibilities") or ""
    ).strip()


async def _usage(db: AsyncSession, user_id: int) -> dict:
    used = await duty_search.used_today(db, user_id)
    return {"used_today": used, "daily_limit": duty_search.DAILY_LIMIT}


@router.post("/duty-search/runs", status_code=202, dependencies=NOT_READ_ONLY)
@limiter.limit("10/minute", key_func=user_or_ip_key)
async def start_duty_search(
    request: Request,
    payload: StartDutySearch,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    _search_access(user)
    goal = (payload.goal or "").strip()
    title = (payload.title or "").strip() or None
    if payload.job_id is not None:
        job = await _authorized_job(db, user, payload.job_id)
        goal = goal or _duties_of(job)
        title = title or job.title
        client_id = job.client_id
        if not goal:
            raise HTTPException(
                422,
                "Champion tej rekrutacji nie ma obowiązków. Uzupełnij je w Profilu "
                "Championa albo opisz cel projektu.",
            )
    else:
        if payload.client_id is None:
            raise HTTPException(
                422,
                "Wskaż klienta — bez niego nie da się sprawdzić NDA, konfliktów "
                "konkurencyjnych ani weta hiring managera.",
            )
        from app.services import review_batch
        from app.services.client_access import assert_client_assignable

        await review_batch.assert_search_allowed(db, user)
        await assert_client_assignable(db, payload.client_id)
        client_id = payload.client_id
    if len(goal) < duty_search.GOAL_MIN_CHARS:
        raise HTTPException(
            422,
            f"Opisz cel albo obowiązki co najmniej {duty_search.GOAL_MIN_CHARS} znakami — "
            "co osoba ma zrobić, w jakiej skali i w jakim środowisku.",
        )
    if client_id is None or not await db.get(Client, client_id):
        raise HTTPException(404, "Klient nie istnieje")

    # Jedna transakcja startu na osobę naraz: dwa równoległe kliknięcia nie
    # ominą limitu dziennego ani dwóch slotów.
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    used = await duty_search.used_today(db, user.id)
    if used >= duty_search.DAILY_LIMIT:
        raise HTTPException(
            429,
            f"Dziś wykorzystano {used} z {duty_search.DAILY_LIMIT} wyszukiwań „Kto już to "
            "robił”. Zapisane wyniki możesz dalej otwierać; nowe jutro.",
        )
    if await duty_search.active_count(db, user.id) >= duty_search.MAX_ACTIVE_PER_USER:
        raise HTTPException(
            409, "Dwa wyszukiwania już trwają. Poczekaj na ich zakończenie."
        )
    run = DutySearchRun(
        id=str(uuid.uuid4()),
        created_by=user.id,
        client_id=client_id,
        job_id=payload.job_id,
        goal_title=title[:300] if title else None,
        goal_text=goal[: duty_search.GOAL_MAX_CHARS],
        state="queued",
        metrics={},
    )
    db.add(run)
    await db.commit()
    return {
        "run_id": run.id,
        "state": run.state,
        "usage": {"used_today": used + 1, "daily_limit": duty_search.DAILY_LIMIT},
    }


async def _visible_run(db: AsyncSession, user, run_id: str) -> DutySearchRun:
    run = await db.get(DutySearchRun, run_id)
    if run is None:
        raise HTTPException(404, "Wyszukiwanie nie istnieje")
    if run.created_by == user.id:
        return run
    if run.job_id is not None:
        try:
            await _authorized_job(db, user, run.job_id)
            return run
        except HTTPException:
            pass
    raise HTTPException(404, "Wyszukiwanie nie istnieje")


async def _payload(db: AsyncSession, run: DutySearchRun, user_id: int) -> dict:
    rows = (
        await db.execute(
            select(DutySearchResult, Candidate)
            .join(Candidate, Candidate.id == DutySearchResult.candidate_id)
            .where(DutySearchResult.run_id == run.id)
            .order_by(DutySearchResult.position)
        )
    ).all()
    results = []
    for result, cand in rows:
        extracted = (
            cand.cv_extracted_data if isinstance(cand.cv_extracted_data, dict) else {}
        )
        a = result.assessment or {}
        results.append(
            {
                "candidate_id": cand.id,
                "name": " ".join(p for p in (cand.name, cand.lastname) if p),
                "position": extracted.get("current_position")
                or cand.linkedin_current_title
                or "",
                "years_it": cand.years_it_experience,
                "tier": result.tier,
                "confidence": result.confidence,
                "fit_score": round(result.fit_score)
                if result.fit_score is not None
                else None,
                "from_goal_only": result.from_goal_only,
                "capabilities": a.get("capabilities") or {},
                "evidence": a.get("evidence") or [],
                "gap": a.get("gap") or "",
                "question": a.get("question") or "",
                "error": a.get("error"),
                "feedback": result.feedback,
            }
        )
    plan = run.plan or {}
    metrics = run.metrics or {}
    return {
        "run_id": run.id,
        "state": run.state,
        "error_code": run.error_code,
        "job_id": run.job_id,
        "client_id": run.client_id,
        "title": run.goal_title,
        "goal": run.goal_text,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "plan": {
            "summary": plan.get("summary") or "",
            "capabilities": plan.get("capabilities") or [],
            "signals": plan.get("signals") or [],
            "anti": plan.get("anti") or [],
        },
        "stats": {
            "judged": metrics.get("judged"),
            "seconds": metrics.get("seconds"),
            "tiers": metrics.get("tiers") or {},
            "plan_ok": metrics.get("plan_ok"),
            "canonical_degraded": metrics.get("canonical_degraded"),
            "judge_errors": metrics.get("judge_errors"),
        },
        "results": results,
        "usage": await _usage(db, user_id),
    }


@router.get("/duty-search/runs/{run_id}")
async def get_duty_search(
    run_id: str, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    _search_access(user)
    run = await _visible_run(db, user, run_id)
    return await _payload(db, run, user.id)


@router.get("/jobs/{job_id}/duty-search/latest")
async def latest_duty_search(
    job_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    _search_access(user)
    job = await _authorized_job(db, user, job_id)
    run = await db.scalar(
        select(DutySearchRun)
        .where(DutySearchRun.job_id == job_id)
        .order_by(DutySearchRun.created_at.desc())
        .limit(1)
    )
    return {
        "has_duties": bool(_duties_of(job)),
        "duties": _duties_of(job),
        "title": job.title,
        "run": await _payload(db, run, user.id) if run else None,
        "usage": await _usage(db, user.id),
    }


@router.put(
    "/duty-search/runs/{run_id}/results/{candidate_id}/feedback",
    dependencies=NOT_READ_ONLY,
)
async def set_feedback(
    run_id: str,
    candidate_id: int,
    body: FeedbackBody,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    _search_access(user)
    await _visible_run(db, user, run_id)
    result = await db.get(DutySearchResult, (run_id, candidate_id))
    if result is None:
        raise HTTPException(404, "Tej osoby nie ma w wyniku")
    result.feedback = body.vote
    result.feedback_by = user.id if body.vote else None
    result.feedback_at = datetime.now(timezone.utc) if body.vote else None
    await db.commit()
    return {"candidate_id": candidate_id, "feedback": result.feedback}
