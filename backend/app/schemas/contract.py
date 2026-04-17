from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.models.contract import ContractStatus, ContractType, ContractWorkMode, RateUnit


class ContractCreate(BaseModel):
    candidate_id: int
    client_id: int
    job_id: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    rate_candidate: Optional[int] = None
    rate_client: Optional[int] = None
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
    rate_candidate: Optional[int] = None
    rate_client: Optional[int] = None
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


class ContractResponse(BaseModel):
    id: int
    candidate_id: int
    client_id: int
    job_id: Optional[int]
    start_date: date
    end_date: Optional[date]
    rate_candidate: Optional[int]
    rate_client: Optional[int]
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
    created_at: datetime
    updated_at: datetime

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
