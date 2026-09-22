"""Router `/api/board-tasks` — kolejka „Czeka na Ciebie" (0348).

Odczyt listy (DZ, do wysłania do Cpro, wysłane do Cpro) i zmiana osoby, która
wysyła kandydata do Cpro. Samo zatwierdzenie DZ i oznaczenie „wysłane" to
zwykły ruch w pipeline (`POST /api/pipeline/move`) — ta trasa nie ma własnej
ścieżki zapisu etapu, żeby reguły ruchu (wersja procesu, ostrzeżenia
dopuszczalności, odznaki) obowiązywały bez kopii.
"""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import CandidateStage
from app.services import board_tasks as svc
from app.services.board_stage_badges import (
    DZ_BADGE_ROLES,
    cpro_enabled_for_client,
    is_cpro_stage,
)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class BoardTaskRow(BaseModel):
    kind: Literal["dz", "cpro_to_send", "cpro_sent"]
    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    since: datetime
    process_state_version: int
    target_stage_def_id: Optional[int] = None
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None


class BoardTasksResponse(BaseModel):
    dz: list[BoardTaskRow]
    cpro_to_send: list[BoardTaskRow]
    cpro_sent: list[BoardTaskRow]
    window_days: int
    can_approve_dz: bool


class CproAssigneeUpdate(BaseModel):
    assignee_id: int


class CproAssigneeResponse(BaseModel):
    stage_id: int
    assignee_id: int
    assignee_name: Optional[str] = None
    added_to_team: bool = False


@router.get("", response_model=BoardTasksResponse)
async def list_board_tasks(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> BoardTasksResponse:
    snapshot = await svc.load_snapshot(db)
    portfolio = await svc.dl_portfolio_client_ids(db, current_user.id)
    mine = svc.tasks_for_user(snapshot, current_user, portfolio=portfolio)
    return BoardTasksResponse(
        dz=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_DZ]],
        cpro_to_send=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_CPRO_TO_SEND]],
        # Najdłużej czekające na Nordeę na górze — wysłane rośnie w czasie.
        cpro_sent=[BoardTaskRow(**t.as_dict()) for t in mine[svc.KIND_CPRO_SENT]],
        window_days=svc.WINDOW_DAYS,
        can_approve_dz=current_user.has_any_role(*DZ_BADGE_ROLES),
    )


@router.patch("/cpro/{stage_id}/assignee", response_model=CproAssigneeResponse)
async def set_cpro_assignee(
    stage_id: int,
    body: CproAssigneeUpdate,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CproAssigneeResponse:
    """Zmienia osobę, która wyśle kandydata do Cpro.

    Działa wyłącznie na BIEŻĄCYM wierszu pary stojącym na „Wysłać do Cpro"
    rekrutacji Nordei — zmiana osoby na historycznym wierszu nie zmieniłaby
    nic, co ktokolwiek widzi.
    """

    row = await db.scalar(
        select(CandidateStage).where(CandidateStage.id == stage_id).with_for_update()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego etapu kandydata.")
    job = await db.get(Job, row.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rekrutacji.")
    await ensure_job_membership(db, current_user, job.id)

    latest_id = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == row.candidate_id,
            CandidateStage.job_id == row.job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    stage_name = (
        await db.scalar(
            select(PipelineStageDef.name).where(PipelineStageDef.id == row.stage_def_id)
        )
        if row.stage_def_id is not None
        else None
    )
    if (
        latest_id != row.id
        or not is_cpro_stage(stage_name)
        or not cpro_enabled_for_client(job.client_id)
    ):
        raise HTTPException(
            status_code=409,
            detail=("Kandydat nie czeka już na wysłanie do Cpro — odśwież listę."),
        )

    assignee = await svc.load_assignee(db, body.assignee_id)
    added = await svc.ensure_assignee_can_move(
        db, job_id=job.id, assignee=assignee, actor=current_user
    )
    previous = row.task_assignee_id
    row.task_assignee_id = assignee.id
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=row.id,
            action="cpro_assignee_changed",
            user_id=current_user.id,
            details={
                "candidate_id": row.candidate_id,
                "job_id": row.job_id,
                "from": previous,
                "to": assignee.id,
                "added_to_team": added,
            },
        )
    )
    if previous != assignee.id:
        candidate = await db.get(Candidate, row.candidate_id)
        name = (
            " ".join(p for p in (candidate.name, candidate.lastname) if p)
            if candidate
            else "Kandydat"
        )
        await svc.notify_cpro_assignment(
            db,
            stage_id=row.id,
            candidate_name=name,
            job_id=job.id,
            job_title=job.title,
            candidate_id=row.candidate_id,
            assignee_id=assignee.id,
            actor=current_user,
        )
    await db.commit()
    return CproAssigneeResponse(
        stage_id=row.id,
        assignee_id=assignee.id,
        assignee_name=assignee.name or assignee.email,
        added_to_team=added,
    )
