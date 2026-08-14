"""Schemas for GET /api/clients/{id}/profile — the aggregated Client Profile tab.

One endpoint returns everything the frontend Profile tab needs:
- `summary` with 5 headline metrics + avg_time_to_fill
- `open_jobs` — aktywne, published
- `active_consultants` — Contract.status in (active, ending)
- `historical.placements` — Contract.status=ended
- `historical.lost_jobs` — Job.status=closed AND no matching Contract

See also: [0037_job_close_reason.py](backend/alembic/versions/0037_job_close_reason.py)
for the Job.close_reason column that powers the lost_jobs section.
"""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel

from app.models.contract import ContractTerminationReason
from app.models.job import JobCloseReason, JobPriority, Seniority
from app.schemas.money import WholePLN


class RecruiterBrief(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None


class CandidateBrief(BaseModel):
    id: int
    name: str
    avatar_url: Optional[str] = None
    competence_category: Optional[str] = None
    linkedin: Optional[str] = None


class ClientProfileSummary(BaseModel):
    open_jobs: int
    active_consultants: int
    total_placements: int  # active + historical (ever placed)
    # R0 (plan 2026-07-16): finanse są Optional — dla ról bez VIEW_FINANCE
    # endpoint redaguje je do None zamiast zwracać kwoty.
    active_mrr: Optional[int] = None  # sum monthly margin for active contracts (PLN)
    ltv: Optional[int] = (
        None  # lifetime revenue (PLN, monthly_rate_client * duration_months)
    )
    avg_time_to_fill_days: Optional[float] = (
        None  # mean (Contract.start_date - Job.created_at) for placed jobs
    )


class OpenJobItem(BaseModel):
    id: int
    title: str
    seniority: Optional[Seniority] = None
    priority: JobPriority
    days_open: int
    candidate_count: int  # distinct candidates in pipeline
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    recruiter: Optional[RecruiterBrief] = None
    created_at: datetime


class ActiveConsultantItem(BaseModel):
    contract_id: int
    candidate: CandidateBrief
    job_id: Optional[int] = None
    job_title: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    days_to_end: Optional[int] = (
        None  # null if no end_date; < 30 triggers amber UI, < 7 red
    )
    monthly_rate_client: Optional[WholePLN] = None
    # Stawka kosztowa /mc (ticket #5 krok 1: koszt + przychód + marża w wierszu).
    # Dane finansowe — redagowane dla ról bez VIEW_FINANCE jak rodzeństwo.
    monthly_rate_candidate: Optional[WholePLN] = None
    monthly_margin: Optional[WholePLN] = None
    currency: str = "PLN"
    # „Część umowy" e-Zdrowia z REPREZENTATYWNEGO zamówienia kontraktu
    # (zamówienie pokrywające dziś, fallback: najnowsze po start_date — ta sama
    # semantyka co FE splitOrders.activeOrder). NULL u innych klientów i gdy
    # część nieuzupełniona. Napędza filtr części w Profil → Obecni konsultanci.
    project_part: Optional[str] = None


class HistoricalPlacementItem(BaseModel):
    """Wiersz zakładki „Archiwum konsultantów" — konsultant po zakończeniu projektu.

    Ten sam komplet kolumn co „Obecni konsultanci" plus data zakończenia. Stawki
    są rozwiązywane na DZIEŃ ZAKOŃCZENIA, nie na dziś: archiwum jest zapisem
    historycznym, a krok harmonogramu zaplanowany po zakończeniu projektu nigdy
    nie obowiązywał w jego trakcie.
    """

    contract_id: int
    candidate: CandidateBrief
    # `job_id` (nie tylko tytuł) — wiersz archiwum linkuje do rekrutacji tak samo
    # jak wiersz aktywnego konsultanta.
    job_id: Optional[int] = None
    job_title: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    terminated_at: Optional[date] = None
    termination_reason: Optional[ContractTerminationReason] = None
    duration_months: Optional[int] = None
    # Dane finansowe — redagowane dla ról bez VIEW_FINANCE, jak w rodzeństwie.
    monthly_rate_client: Optional[WholePLN] = None
    monthly_rate_candidate: Optional[WholePLN] = None
    monthly_margin: Optional[WholePLN] = None
    total_revenue: Optional[int] = None  # monthly_rate_client * duration_months (PLN)


class LostJobItem(BaseModel):
    job_id: int
    title: str
    closed_at: Optional[datetime] = None
    close_reason: Optional[JobCloseReason] = None
    close_notes: Optional[str] = None
    candidate_count_reached: int  # how many candidates ever entered the pipeline


class ClientProfileHistory(BaseModel):
    placements: List[HistoricalPlacementItem]
    lost_jobs: List[LostJobItem]


class ClientProfileResponse(BaseModel):
    summary: ClientProfileSummary
    open_jobs: List[OpenJobItem]
    active_consultants: List[ActiveConsultantItem]
    historical: ClientProfileHistory
