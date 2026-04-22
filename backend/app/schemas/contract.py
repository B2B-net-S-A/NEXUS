from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.models.contract import (
    ContractStatus,
    ContractTerminationReason,
    ContractType,
    ContractWorkMode,
    RateUnit,
)


class ContractCreate(BaseModel):
    candidate_id: int
    client_id: int
    job_id: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    client_order_end_date: Optional[date] = None
    rate_candidate: Optional[int] = None
    rate_client: Optional[int] = None
    target_rate_min: Optional[int] = None
    target_rate_max: Optional[int] = None
    currency: str = "PLN"
    rate_unit: RateUnit = RateUnit.monthly
    billing_hours_per_month: int = 160
    contract_type: ContractType = ContractType.b2b
    status: ContractStatus = ContractStatus.draft
    documents: Optional[Any] = None
    client_pm_name: Optional[str] = None
    client_pm_email: Optional[str] = None
    work_mode: Optional[ContractWorkMode] = None
    office_location: Optional[str] = None
    team_name: Optional[str] = None
    project_name: Optional[str] = None
    handover_notes: Optional[str] = None


class ContractUpdate(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    client_order_end_date: Optional[date] = None
    rate_candidate: Optional[int] = None
    rate_client: Optional[int] = None
    target_rate_min: Optional[int] = None
    target_rate_max: Optional[int] = None
    currency: Optional[str] = None
    rate_unit: Optional[RateUnit] = None
    billing_hours_per_month: Optional[int] = None
    contract_type: Optional[ContractType] = None
    status: Optional[ContractStatus] = None
    documents: Optional[Any] = None
    client_pm_name: Optional[str] = None
    client_pm_email: Optional[str] = None
    work_mode: Optional[ContractWorkMode] = None
    office_location: Optional[str] = None
    team_name: Optional[str] = None
    project_name: Optional[str] = None
    handover_notes: Optional[str] = None
    termination_reason: Optional[ContractTerminationReason] = None
    termination_lessons: Optional[str] = None
    terminated_at: Optional[date] = None


class ContractResponse(BaseModel):
    id: int
    candidate_id: int
    client_id: int
    job_id: Optional[int]
    start_date: date
    end_date: Optional[date]
    client_order_end_date: Optional[date] = None
    rate_candidate: Optional[int]
    rate_client: Optional[int]
    target_rate_min: Optional[int] = None
    target_rate_max: Optional[int] = None
    currency: str
    rate_unit: RateUnit
    billing_hours_per_month: int
    margin: Optional[int]
    contract_type: ContractType
    status: ContractStatus
    documents: Optional[Any]
    client_pm_name: Optional[str] = None
    client_pm_email: Optional[str] = None
    work_mode: Optional[ContractWorkMode] = None
    office_location: Optional[str] = None
    team_name: Optional[str] = None
    project_name: Optional[str] = None
    handover_notes: Optional[str] = None
    termination_reason: Optional[ContractTerminationReason] = None
    termination_lessons: Optional[str] = None
    terminated_at: Optional[date] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContractTerminateRequest(BaseModel):
    """Payload dla dedykowanego POST /{id}/terminate."""

    termination_reason: ContractTerminationReason
    termination_lessons: Optional[str] = None
    terminated_at: Optional[date] = None  # default = today


class ContractBenchmarkComparison(BaseModel):
    """Porównanie stawki kontraktu vs nasza średnia vs rynek."""

    contract_rate_monthly: Optional[int] = None
    internal_avg_monthly: Optional[int] = None
    internal_median_monthly: Optional[int] = None
    internal_sample_size: int = 0
    market_min: Optional[int] = None
    market_median: Optional[int] = None
    market_max: Optional[int] = None
    market_source: Optional[str] = None
    market_source_date: Optional[date] = None
    role_used: Optional[str] = None
    currency: str = "PLN"


class ContractTimelineItem(BaseModel):
    """Połączony feed notes+calls per kontrakt (timeline)."""

    id: int
    kind: str  # "note" | "call"
    at: datetime
    summary: Optional[str] = None
    content: Optional[str] = None
    sub_type: Optional[str] = None  # note_type lub direction
    status: Optional[str] = None
    author_id: Optional[int] = None
    author_name: Optional[str] = None
    duration_seconds: Optional[int] = None

    model_config = {"from_attributes": True}


class ContractList(BaseModel):
    items: list[ContractResponse]
    total: int
    page: int
    page_size: int


class ContractDetailResponse(ContractResponse):
    """Extended response for the contract detail page — includes denormalized names."""

    candidate_name: Optional[str] = None
    client_name: Optional[str] = None
    job_title: Optional[str] = None
    monthly_rate_candidate: Optional[int] = None
    monthly_rate_client: Optional[int] = None
    monthly_margin: Optional[int] = None

    model_config = {"from_attributes": True}


class ContractActivityEntry(BaseModel):
    id: int
    action: str
    details: Optional[Any] = None
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractRateHistoryEntry(BaseModel):
    id: int
    rate: int
    currency: str
    contract_type: str
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
