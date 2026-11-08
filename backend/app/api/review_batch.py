"""Router `/api/review-batch` — porcja dnia od Nexusa (decyzje Artura 07.11.2026).

Stan porcji osoby (licznik w pasku, kafel pulpitu), kolejka przeglądu,
„Dodaj 20 kolejnych” w rekrutacji i ustawienie minimum (HoR). Same decyzje
to zwykłe ruchy w pipeline (`POST /api/pipeline/move`, odrzucenie z powodem
osoby od systemu), żeby reguły ruchu obowiązywały bez kopii. Reguła:
`docs/claude/rekrutacja-tablica/porcja-dnia-minimum-przed-wyszukiwaniem.md`.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus, OperationalUser
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.services import review_batch as svc

router = APIRouter(
    prefix="/api/review-batch",
    tags=["review-batch"],
    dependencies=PIPELINE_SECTION_DEPENDENCIES,
)


class SettingsIn(BaseModel):
    minimum: int = Field(ge=1, le=svc.MAX_MINIMUM)
    # Brak pola = bez zmiany (stary front wysyła samo minimum).
    block_enabled: Optional[bool] = None
    pilot_user_ids: Optional[list[int]] = Field(default=None, max_length=200)


@router.get("/me")
async def my_batch(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """Stan porcji: minimum, decyzje dziś, czekające osoby per rekrutacja."""
    status = await svc.status_for(db, current_user, now=datetime.now(timezone.utc))
    return status.as_dict()


def _position(candidate: Candidate) -> Optional[str]:
    data = (
        candidate.cv_extracted_data
        if isinstance(candidate.cv_extracted_data, dict)
        else {}
    )
    value = data.get("current_position") or candidate.linkedin_current_title
    return str(value)[:120] if value else None


@router.get("/me/queue")
async def my_queue(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    """Osoby z porcji w kolejności przeglądu (rekrutacje na zmianę, w każdej
    od najlepszej). Każdy wiersz niesie migawkę karty i id etapu do ruchu."""
    now = datetime.now(timezone.utc)
    cards = await svc.review_queue(db, current_user, now=now, limit=limit)
    if not cards:
        return {"items": []}
    candidate_ids = {c.candidate_id for c in cards}
    job_ids = {c.job_id for c in cards}
    candidates = {
        c.id: c
        for c in (
            await db.scalars(select(Candidate).where(Candidate.id.in_(candidate_ids)))
        ).all()
    }
    jobs = {
        j.id: j
        for j in (await db.scalars(select(Job).where(Job.id.in_(job_ids)))).all()
    }
    metas = dict(
        (
            await db.execute(
                select(RecruitmentProcess.id, RecruitmentProcess.entry_meta).where(
                    RecruitmentProcess.id.in_([c.process_id for c in cards])
                )
            )
        ).all()
    )
    stage_rows = (
        await db.execute(
            select(
                CandidateStage.id, CandidateStage.job_id, CandidateStage.candidate_id
            )
            .where(
                CandidateStage.job_id.in_(job_ids),
                CandidateStage.candidate_id.in_(candidate_ids),
            )
            .order_by(CandidateStage.moved_at.asc(), CandidateStage.id.asc())
        )
    ).all()
    latest_stage = {(job_id, cid): sid for sid, job_id, cid in stage_rows}
    items = []
    for card in cards:
        person = candidates.get(card.candidate_id)
        job = jobs.get(card.job_id)
        if person is None or job is None:
            continue
        meta = metas.get(card.process_id) or {}
        items.append(
            {
                "process_id": card.process_id,
                "stage_id": latest_stage.get((card.job_id, card.candidate_id)),
                "job_id": job.id,
                "job_title": job.title or "",
                "candidate_id": person.id,
                "name": person.name,
                "city": person.city,
                "years": person.years_it_experience,
                "position": _position(person),
                "score": card.score,
                "matched_must": meta.get("matched_must") or [],
                "missing_must": meta.get("missing_must") or [],
                "rate_from_hourly": meta.get("rate_from_hourly"),
                "rate_currency": meta.get("rate_currency"),
                "availability_status": meta.get("availability_status"),
                "cautions": meta.get("cautions") or [],
                "budget_hourly": (
                    float(job.rate_budget_hourly)
                    if job.rate_budget_hourly is not None
                    else None
                ),
            }
        )
    return {"items": items}


@router.post("/jobs/{job_id}/more")
async def add_more(
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """„Dodaj 20 kolejnych”: tylko rekruter tej rekrutacji, gdy jego część
    porcji w niej jest przejrzana. Nowe osoby trafiają do klikającego."""
    from app.services.new_column_autofill import fill_job

    if not svc.enabled():
        raise HTTPException(status_code=409, detail="Porcja dnia jest wyłączona.")
    team = (await svc.recruiter_ids_for_jobs(db, [job_id])).get(job_id, [])
    if current_user.id not in team:
        raise HTTPException(
            status_code=403,
            detail="Kolejne osoby dobiera rekruter przypisany do tej rekrutacji.",
        )
    now = datetime.now(timezone.utc)
    mine = svc.batch_cards(
        await svc.pending_cards(db, job_ids=[job_id], owner_id=current_user.id), now
    )
    if mine:
        raise HTTPException(
            status_code=409,
            detail=f"Najpierw przejrzyj swoje osoby w tej rekrutacji ({len(mine)}).",
        )
    added = await fill_job(
        db,
        job_id,
        now=now,
        batch=True,
        extra_for=current_user.id,
    )
    await db.commit()
    return {"added": len(added)}


@router.get("/settings")
async def get_settings(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    value = await svc.read_settings(db)
    out = {
        **value.as_dict(),
        "batch_size": svc.BATCH_SIZE,
        "min_score": svc.MIN_SCORE,
        "max_age_days": svc.MAX_AGE_DAYS,
        "enabled": svc.enabled(),
    }
    if svc.can_edit_settings(current_user):
        # Lista do wyboru pilota — tylko dla tych, którzy ją ustawiają.
        out["recruiters"] = await svc.batch_recruiters(db)
    return out


@router.put("/settings")
async def put_settings(
    payload: SettingsIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Minimum decyzji dziennie, wyłącznik blokady i pilot — ustawia Head of
    Recruitment i admin."""
    current = await svc.read_settings(db)
    value = svc.BatchSettings(
        minimum=payload.minimum,
        block_enabled=(
            current.block_enabled
            if payload.block_enabled is None
            else payload.block_enabled
        ),
        pilot_user_ids=(
            current.pilot_user_ids
            if payload.pilot_user_ids is None
            else tuple(sorted(set(payload.pilot_user_ids)))
        ),
    )
    error = svc.validation_error(value)
    if error:
        raise HTTPException(status_code=422, detail=error)
    await svc.write_settings(db, value, user_id=current_user.id)
    await db.commit()
    return value.as_dict()
