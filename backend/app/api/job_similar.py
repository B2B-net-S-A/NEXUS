"""Podobne rekrutacje, przepięcia i „Mamy championa" (migracja 0341).

* ``GET  /api/jobs/{id}/similar`` — połączone rekrutacje + sugestie systemu.
* ``POST /api/jobs/{id}/similar`` — połącz (oba kierunki) i od razu przepnij
  osoby wysłane wcześniej do klienta do „Do przejrzenia".
* ``DELETE /api/jobs/{id}/similar/{other_id}`` — rozłącz (propozycje zostają).
* ``POST /api/job-similarity/preview`` — sugestie dla rekrutacji jeszcze
  niezapisanej (strona „Nowa rekrutacja").
* ``POST /api/jobs/{id}/champion-found`` — Delivery Lead: „Mamy championa"
  (albo cofnięcie). Do tej chwili status requestu to „Szukamy".

Uwaga: moduł bez ``from __future__ import annotations`` — slowapi/FastAPI
czytają adnotacje ciała w czasie rejestracji trasy.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus, get_db
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.activity import Activity
from app.models.client import Client
from app.models.job import Job
from app.models.user import UserRole
from app.services import job_similarity as sim

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

MAX_LINKS_PER_CALL = 20


async def _job(db: AsyncSession, user, job_id: int) -> Job:
    from app.api.candidate_search import (  # noqa: PLC0415
        _authorized_job,
        _search_access,
    )

    _search_access(user)
    return await _authorized_job(db, user, job_id)


async def _job_briefs(db: AsyncSession, job_ids: list[int]) -> dict[int, dict]:
    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(
                Job.id,
                Job.title,
                Job.reference_number,
                Job.status,
                Job.closed_at,
                func.coalesce(Client.display_name, Client.name),
            )
            .outerjoin(Client, Client.id == Job.client_id)
            .where(Job.id.in_(job_ids))
        )
    ).all()
    return {
        row[0]: {
            "id": row[0],
            "title": row[1],
            "reference_number": row[2],
            "status": row[3].value if hasattr(row[3], "value") else row[3],
            "closed_at": row[4],
            "client_name": row[5],
        }
        for row in rows
    }


async def _payload(db: AsyncSession, job: Job) -> dict:
    linked_ids = (await sim.linked_job_ids(db, [job.id])).get(job.id, [])
    suggestions = await sim.suggestions_for_job(db, job, exclude=linked_ids)
    ids = list({*linked_ids, *(p.id for p, _ in suggestions)})
    briefs = await _job_briefs(db, ids)
    sent = await sim.sent_counts(db, ids)
    scores = {p.id: score for p, score in suggestions}
    reassigned = (await sim.reassign_counts(db, [job.id])).get(job.id, 0)

    def item(job_id: int, linked: bool) -> Optional[dict]:
        brief = briefs.get(job_id)
        if brief is None:
            return None
        return {
            **brief,
            "similarity": scores.get(job_id),
            "sent_count": sent.get(job_id, 0),
            "linked": linked,
        }

    return {
        "job_id": job.id,
        "reassigned_count": reassigned,
        "linked": [x for x in (item(i, True) for i in linked_ids) if x],
        "suggestions": [x for x in (item(p.id, False) for p, _ in suggestions) if x],
    }


@router.get("/jobs/{job_id}/similar")
async def get_similar_jobs(
    job_id: int, user: RecruiterPlus, db: AsyncSession = Depends(get_db)
):
    job = await _job(db, user, job_id)
    return await _payload(db, job)


class LinkSimilarBody(BaseModel):
    job_ids: list[int] = Field(..., min_length=1, max_length=MAX_LINKS_PER_CALL)


@router.post("/jobs/{job_id}/similar")
async def link_similar_jobs(
    job_id: int,
    body: LinkSimilarBody,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    wanted = sorted({i for i in body.job_ids if i != job_id})
    known = set((await db.execute(select(Job.id).where(Job.id.in_(wanted)))).scalars())
    missing = [i for i in wanted if i not in known]
    if missing:
        raise HTTPException(404, f"Nie ma rekrutacji: {', '.join(map(str, missing))}")
    # audyt 22.09 r2 (SEC-05): połączenie przepina osoby wysłane do klienta
    # w OBU kierunkach, więc wymaga dostępu także do drugiej rekrutacji —
    # inaczej rekruter spoza jej zespołu dostawał wgląd w jej wysłanych.
    for other_id in wanted:
        await _job(db, user, other_id)
        await ensure_job_membership(db, user, other_id)
    linked, reassigned = await sim.link_jobs(db, job_id, wanted, user_id=user.id)
    db.add(
        Activity(
            entity_type="job",
            entity_id=job_id,
            action="similar_jobs_linked",
            user_id=user.id,
            details={"job_ids": wanted, "reassigned": reassigned},
        )
    )
    await db.commit()
    payload = await _payload(db, job)
    return {**payload, "linked_now": linked, "reassigned_now": reassigned}


@router.delete("/jobs/{job_id}/similar/{other_id}")
async def unlink_similar_job(
    job_id: int,
    other_id: int,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    removed = await sim.unlink_jobs(db, job_id, other_id)
    if removed:
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="similar_jobs_unlinked",
                user_id=user.id,
                details={"job_id": other_id},
            )
        )
    await db.commit()
    return await _payload(db, job)


class SimilarPreviewBody(BaseModel):
    title: str = Field("", max_length=300)
    must_skills: list[str] = Field(default_factory=list, max_length=60)
    competence_category_id: Optional[int] = None


class _Draft:
    """Rekrutacja jeszcze niezapisana — tyle, ile potrzebuje miara podobieństwa."""

    def __init__(self, body: SimilarPreviewBody) -> None:
        self.id = 0
        self.title = body.title
        self.must_skills = [s for s in body.must_skills if s.strip()]
        self.competence_category_id = body.competence_category_id
        self.client_id = None
        self.reference_number = None
        self.status = None
        self.created_at = None


@router.post("/job-similarity/preview")
async def preview_similar_jobs(
    body: SimilarPreviewBody,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    if not body.title.strip() and not body.must_skills:
        return {"suggestions": []}
    suggestions = await sim.suggestions_for_job(db, _Draft(body))
    ids = [p.id for p, _ in suggestions]
    briefs = await _job_briefs(db, ids)
    sent = await sim.sent_counts(db, ids)
    return {
        "suggestions": [
            {
                **briefs[p.id],
                "similarity": score,
                "sent_count": sent.get(p.id, 0),
                "linked": False,
            }
            for p, score in suggestions
            if p.id in briefs
        ]
    }


class ChampionFoundBody(BaseModel):
    found: bool = True


_CHAMPION_ROLES = (UserRole.admin, UserRole.delivery_lead, UserRole.head_of_recruitment)


@router.post("/jobs/{job_id}/champion-found")
async def set_champion_found(
    job_id: int,
    body: ChampionFoundBody,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    if not user.has_any_role(*_CHAMPION_ROLES):
        raise HTTPException(
            403,
            "„Mamy championa” oznacza Delivery Lead (albo admin / Head of Recruitment).",
        )
    await _job(db, user, job_id)
    await ensure_job_membership(db, user, job_id)
    job = await db.get(Job, job_id, with_for_update=True)
    if job is None:
        raise HTTPException(404, "Rekrutacja nie istnieje")
    changed = (job.champion_found_at is not None) != body.found
    if changed:
        job.champion_found_at = datetime.now(timezone.utc) if body.found else None
        job.champion_found_by = user.id if body.found else None
        db.add(
            Activity(
                entity_type="job",
                entity_id=job_id,
                action="champion_found_changed",
                user_id=user.id,
                details={"found": body.found},
            )
        )
    await db.commit()
    return {
        "job_id": job_id,
        "champion_found": job.champion_found_at is not None,
        "champion_found_at": job.champion_found_at,
        "changed": changed,
    }
