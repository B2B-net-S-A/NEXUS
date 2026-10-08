"""Przegląd Delivery Leada przed wysłaniem CV — ``/api/dl-review`` (D6, D9, D10).

* ``GET /dl-review/context?candidate_id&job_id`` — wymagania klienta a
  kandydat (z dowodem i źródłem), ocena rekrutera z formularza screeningu,
  ryzyka i historia u klienta, stawka kandydata, budżet od–do, podpowiedź
  stawki do klienta, agregaty konsultantów u klienta (mediana marży),
  poprzednie wysyłki, inni wysłani w tej rekrutacji, ostatni kontrakt,
  lista pól do „Wróć do poprawy”.
* ``GET /dl-review/jobs/{job_id}/queue`` — porównanie osób czekających na
  przegląd w jednej rekrutacji (D10): ocena rekrutera, wymagania X/Y, koszt,
  start, ryzyka, ile czeka, rundy poprawek. U Nordei pusto (tam CV idzie do
  Cpro, przeglądu DL nie ma).

Bramka jak wysyłka do klienta (uprawnienie ``recruitment_manage``) i odczyt
rekrutacji. Trasy tylko czytają. Kwoty i stawki do klienta redaguje serwis
(``services/dl_review.py``) — zobacz tam reguły.
"""

from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.board_tasks import BoardTaskRow
from app.api.deps import OperationalUser
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.user import User
from app.services import board_tasks as board_tasks_svc
from app.services import dl_review as svc
from app.services import move_requirements
from app.services.action_permissions import ProductAction, has_permission
from app.services.board_stage_badges import cpro_enabled_for_client

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

FORBIDDEN = "Przegląd przed wysłaniem do klienta robi Delivery Lead."


class RateOut(BaseModel):
    amount: float
    unit: str
    currency: str
    hourly_pln: Optional[float] = None
    at: Optional[datetime] = None


class ClientRateHintOut(RateOut):
    source: Literal["this_pair", "same_client"]
    job_id: Optional[int] = None
    job_title: Optional[str] = None


class RequirementOut(BaseModel):
    key: str
    label: str
    level: Literal["critical", "must", "nice", "experience"]
    # met | missing | unknown (nie da się sprawdzić słowem — ocenia DL)
    status: Literal["met", "missing", "unknown"]
    sources: list[str]
    candidate_value: Optional[str] = None


class AssessmentAnswerOut(BaseModel):
    question: Optional[str] = None
    question_id: Optional[str] = None
    answer: str
    deal_breaker_hit: bool


class AssessmentOut(BaseModel):
    overall_fit: Optional[str] = None
    overall_fit_label: Optional[str] = None
    fields: dict[str, Optional[str]]
    answers: list[AssessmentAnswerOut]


class RiskOut(BaseModel):
    code: str
    label: str
    severity: Literal["high", "medium", "info"]


class SendOut(BaseModel):
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: Optional[str] = None
    client_name: Optional[str] = None
    sent_at: Optional[datetime] = None
    outcome: Optional[str] = None
    same_client: bool
    candidate_rate: Optional[RateOut] = None
    client_rate: Optional[RateOut] = None


class ClientRatesOut(BaseModel):
    """Agregaty konsultantów u klienta — bez nazwisk."""

    consultants: int
    client_margin_median_hourly: Optional[float] = None
    category_name: Optional[str] = None
    category_count: int
    category_cost_min: Optional[float] = None
    category_cost_max: Optional[float] = None
    category_revenue_min: Optional[float] = None
    category_revenue_max: Optional[float] = None
    category_margin_median_hourly: Optional[float] = None


class LastContractOut(BaseModel):
    client_name: Optional[str] = None
    status: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    cost_hourly: Optional[float] = None
    redacted: bool


class BudgetOut(BaseModel):
    min_hourly: Optional[float] = None
    max_hourly: Optional[float] = None


class FixOptionOut(BaseModel):
    key: str
    label: str
    group: Literal["answers", "terms", "assessment", "rate", "cv"]


class DlReviewContext(BaseModel):
    candidate_id: int
    candidate_name: str
    job_id: int
    stage_id: Optional[int] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    category_name: Optional[str] = None
    qc_status: str
    qc_blocking_failed: int = 0
    can_see_amounts: bool
    can_see_client_rates: bool
    candidate_rate: Optional[RateOut] = None
    rate_from_hourly: Optional[float] = None
    budget: BudgetOut
    client_rate_hint: Optional[ClientRateHintOut] = None
    client_rates: Optional[ClientRatesOut] = None
    requirements: list[RequirementOut]
    requirements_met: int
    requirements_total: int
    assessment: AssessmentOut
    risks: list[RiskOut]
    start: Optional[str] = None
    fix_rounds: int
    previous_sends: list[SendOut]
    job_sends: list[SendOut]
    last_contract: Optional[LastContractOut] = None
    fix_options: list[FixOptionOut]


class DlReviewQueueItem(BaseModel):
    candidate_id: int
    candidate_name: str
    stage_id: Optional[int] = None
    since: datetime
    qc_status: Optional[str] = None
    overall_fit: Optional[str] = None
    overall_fit_label: Optional[str] = None
    requirements_met: int
    requirements_total: int
    candidate_rate: Optional[RateOut] = None
    start: Optional[str] = None
    risks: list[RiskOut]
    fix_rounds: int
    # Ten sam wiersz co pulpit — klik w osobę otwiera przegląd bez drugiego żądania.
    task: BoardTaskRow


class DlReviewQueue(BaseModel):
    job_id: int
    # Nordea: CV idzie do Cpro, przeglądu DL nie ma — lista zawsze pusta.
    cpro_client: bool
    items: list[DlReviewQueueItem]
    total: int
    limit: int


def _assert_reviewer(user: User) -> None:
    if not has_permission(user, ProductAction.recruitment_manage):
        raise HTTPException(status_code=403, detail=FORBIDDEN)


async def _job(db: AsyncSession, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    return job


@router.get("/dl-review/context", response_model=DlReviewContext)
async def get_dl_review_context(
    user: OperationalUser,
    candidate_id: int = Query(..., gt=0),
    job_id: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
) -> Any:
    _assert_reviewer(user)
    await ensure_job_read_access(db, user, job_id)
    job = await _job(db, job_id)
    if await db.get(Candidate, candidate_id) is None:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje.")
    try:
        return await svc.build_context(
            db, user=user, job=job, candidate_id=candidate_id
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=404, detail="Tej osoby nie ma w rekrutacji."
        ) from exc


@router.get("/dl-review/jobs/{job_id}/queue", response_model=DlReviewQueue)
async def get_dl_review_queue(
    job_id: int,
    user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> Any:
    _assert_reviewer(user)
    await ensure_job_read_access(db, user, job_id)
    job = await _job(db, job_id)
    if cpro_enabled_for_client(job.client_id):
        return DlReviewQueue(
            job_id=job_id, cpro_client=True, items=[], total=0, limit=svc.QUEUE_LIMIT
        )
    snapshot = await board_tasks_svc.load_snapshot(db, job_id=job_id)
    tasks = [
        t
        for t in snapshot.tasks
        if t.kind == board_tasks_svc.KIND_DL_REVIEW and t.job_id == job_id
    ]
    shown = tasks[: svc.QUEUE_LIMIT]
    rows = await svc.build_queue(db, user=user, job=job, tasks=shown)
    cvs = await move_requirements.company_cv_refs(
        db, [(t.candidate_id, t.job_id) for t in shown]
    )
    by_candidate = {t.candidate_id: t for t in shown}
    items = []
    for row in rows:
        task = by_candidate[row["candidate_id"]]
        items.append(
            DlReviewQueueItem(
                **row,
                task=BoardTaskRow(
                    **task.as_dict(),
                    cv_stage_id=(cvs.get((task.candidate_id, task.job_id)) or {}).get(
                        "stage_id"
                    ),
                ),
            )
        )
    return DlReviewQueue(
        job_id=job_id,
        cpro_client=False,
        items=items,
        total=len(tasks),
        limit=svc.QUEUE_LIMIT,
    )
