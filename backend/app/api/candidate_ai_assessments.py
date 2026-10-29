"""„Oceń z AI” na zaznaczonych osobach w rekrutacji (0618).

Dostęp jak dodanie kandydata do rekrutacji (``proposals/bulk``): sekcja
Pipeline (zależności routera), ``RecruiterPlus`` i członkostwo w zespole
rekrutacji (``ensure_job_membership``). Ocena to dodatek do „Dodaj do
Nowych” — kto nie może dodać, nie zleca też oceny.

Przeglądarka wysyła zaznaczenie paczkami po ``MAX_PER_REQUEST`` osób z tym
samym ``batch_id``; ``GET …/latest`` oddaje ostatnią paczkę tej osoby, żeby po
zamknięciu panelu wrócić do wyniku bez ponownego wywołania modelu. Odpowiedź
niesie imię, nazwisko i cytaty — bez e-maila, telefonu i treści CV.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus, get_db
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.candidate import Candidate
from app.models.candidate_ai_assessment import CandidateAiAssessment
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.services import candidate_ai_assessment as svc

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class AssessRequest(BaseModel):
    batch_id: str = Field(..., min_length=36, max_length=36)
    candidate_ids: list[int] = Field(..., min_length=1, max_length=svc.MAX_PER_REQUEST)
    # Miejsce pierwszej osoby paczki w całym zaznaczeniu (remis w kolejności).
    first_index: int = Field(0, ge=0, lt=svc.MAX_BATCH)
    # „Oceń jeszcze raz” — bez przepisania ocen sprzed < 24 h.
    refresh: bool = False

    @field_validator("batch_id")
    @classmethod
    def _uuid(cls, value: str) -> str:
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise ValueError("batch_id musi być identyfikatorem UUID") from exc


def _error_kind(row: CandidateAiAssessment) -> Optional[str]:
    if row.verdict is not None:
        return None
    return "no_cv" if row.error == svc.ERROR_NO_CV else "model"


def _row(row: CandidateAiAssessment, names: dict[int, str], in_job: set[int]) -> dict:
    return {
        "candidate_id": row.candidate_id,
        "full_name": names.get(row.candidate_id) or f"Kandydat #{row.candidate_id}",
        "selection_index": row.selection_index,
        "verdict": row.verdict,
        "strength": row.strength,
        "must_found": row.must_found,
        "must_total": row.must_total,
        "reasons": [
            {
                "text": str(r.get("text") or ""),
                "quote": str(r.get("quote") or ""),
                "source": r.get("source") or svc.SOURCE_CV,
            }
            for r in (row.reasons or [])
            if isinstance(r, dict) and r.get("text") and r.get("quote")
        ],
        "error_kind": _error_kind(row),
        "reused": row.reused_from_id is not None,
        # Osoba ma już kartę w tej rekrutacji — panel nie proponuje jej dodania.
        "in_job": row.candidate_id in in_job,
    }


async def _payload(
    db: AsyncSession, rows: list[CandidateAiAssessment], user_id: int
) -> dict:
    ids = sorted({r.candidate_id for r in rows})
    names = (
        {
            cid: " ".join(p for p in (first, last) if p).strip()
            for cid, first, last in (
                await db.execute(
                    select(Candidate.id, Candidate.name, Candidate.lastname).where(
                        Candidate.id.in_(ids)
                    )
                )
            ).all()
        }
        if ids
        else {}
    )
    in_job = (
        set(
            (
                await db.scalars(
                    select(CandidateStage.candidate_id)
                    .where(
                        CandidateStage.job_id == rows[0].job_id,
                        CandidateStage.candidate_id.in_(ids),
                    )
                    .distinct()
                )
            ).all()
        )
        if ids
        else set()
    )
    used = await svc.used_today(db, user_id)
    ordered = sorted((_row(r, names, in_job) for r in rows), key=svc.call_order_key)
    return {
        "batch_id": rows[0].batch_id if rows else None,
        "created_at": max(r.created_at for r in rows).isoformat() if rows else None,
        "rows": ordered,
        "daily_limit": svc.DAILY_PEOPLE_LIMIT,
        "remaining_today": max(0, svc.DAILY_PEOPLE_LIMIT - used),
    }


async def _job(db: AsyncSession, user, job_id: int) -> Job:
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rekrutacji.")
    await ensure_job_membership(db, user, job_id)
    return job


@router.post(
    "/jobs/{job_id}/ai-assessments",
    summary="„Oceń z AI” — paczka zaznaczonych osób (Dzwoń / Może / Nie pasuje)",
)
async def assess_candidates(
    job_id: int,
    body: AssessRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await _job(db, current_user, job_id)
    # Id z góry: awaria przed modelem kończy się w serwisie `rollback()`, który
    # wygasza obiekty sesji (także konto), a leniwe odświeżenie = MissingGreenlet.
    user_id = current_user.id
    already = int(
        await db.scalar(
            select(func.count(CandidateAiAssessment.id)).where(
                CandidateAiAssessment.batch_id == body.batch_id,
                CandidateAiAssessment.assessed_by == user_id,
            )
        )
        or 0
    )
    if already + len(set(body.candidate_ids)) > svc.MAX_BATCH:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "ai_assessment_batch_too_big",
                "message": f"Naraz oceniamy najwyżej {svc.MAX_BATCH} osób.",
            },
        )
    try:
        await svc.assess(
            db,
            job=job,
            user=current_user,
            batch_id=body.batch_id,
            candidate_ids=body.candidate_ids,
            first_index=body.first_index,
            refresh=body.refresh,
        )
    except svc.DailyLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "ai_assessment_daily_limit",
                "message": (
                    f"Dzienny limit oceny AI to {svc.DAILY_PEOPLE_LIMIT} osób. "
                    f"Dziś zostało {exc.remaining}."
                ),
                "remaining_today": exc.remaining,
            },
        ) from exc
    rows = await svc.batch_rows(
        db, job_id=job_id, user_id=user_id, batch_id=body.batch_id
    )
    return await _payload(db, rows, user_id)


@router.get(
    "/jobs/{job_id}/ai-assessments/latest",
    summary="Ostatnia ocena „Oceń z AI” tej osoby w rekrutacji (≤ 7 dni)",
)
async def latest_assessment(
    job_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    await _job(db, current_user, job_id)
    rows = await svc.batch_rows(db, job_id=job_id, user_id=current_user.id)
    return await _payload(db, rows, current_user.id)
