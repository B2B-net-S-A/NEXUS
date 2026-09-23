"""`GET /api/pipeline/move-requirements` — co jest potrzebne do ruchu (v5).

Okno „Przesuń dalej" pyta, czego brakuje, ZANIM rekruter kliknie — zamiast
dowiadywać się o tym z odmowy serwera po upuszczeniu karty. Reguła „co do
której kolumny" żyje w `services/move_requirements.py`; ta trasa tylko
sprawdza dostęp, ładuje fakty i zwraca wynik. Tylko odczyt.
"""

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef
from app.services import move_requirements

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class MoveRequirementAction(BaseModel):
    kind: Optional[str] = None
    label: Optional[str] = None
    stage_id: Optional[int] = None
    event_id: Optional[int] = None


class MoveRequirementItem(BaseModel):
    key: str
    label: str
    detail: Optional[str] = None
    status: Literal["ok", "missing", "waiting"]
    blocking: bool
    action: Optional[MoveRequirementAction] = None
    column: Optional[str] = None


class MovePrimary(BaseModel):
    kind: Literal["move", "hand_to_dl", "hand_to_cpro", "blocked"]
    label: str
    target_stage_def_id: Optional[int] = None


class MoveRequirementsResponse(BaseModel):
    from_column: Optional[str] = None
    to_column: str
    skipped_columns: list[str]
    items: list[MoveRequirementItem]
    primary: MovePrimary
    owner_note: Optional[str] = None


@router.get("/move-requirements", response_model=MoveRequirementsResponse)
async def get_move_requirements(
    current_user: OperationalUser,
    candidate_id: int = Query(..., ge=1),
    job_id: int = Query(..., ge=1),
    to_stage_def_id: int = Query(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> Any:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rekrutacji.")
    await ensure_job_read_access(db, current_user, job.id)
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego kandydata.")
    stage_def = await db.get(PipelineStageDef, to_stage_def_id)
    if stage_def is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego etapu.")
    # Etap docelowy bywa z innego szablonu niż bieżący wiersz pary (import
    # Traffita) — kolumnę liczymy z samego etapu, tą samą regułą co Tablica.
    to_column = move_requirements.stage_def_column(stage_def)
    facts = await move_requirements.load_pair_facts(
        db, candidate=candidate, job=job, user=current_user
    )
    return move_requirements.build_requirements(facts, to_column)
