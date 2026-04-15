from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.models.contract import ContractStatus, ContractType


class ContractCreate(BaseModel):
    candidate_id: int
    client_id: int
    job_id: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    rate_candidate: Optional[int] = None
    rate_client: Optional[int] = None
    currency: str = "PLN"
    contract_type: ContractType = ContractType.b2b
    status: ContractStatus = ContractStatus.draft
    documents: Optional[Any] = None


class ContractUpdate(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    rate_candidate: Optional[int] = None
    rate_client: Optional[int] = None
    currency: Optional[str] = None
    contract_type: Optional[ContractType] = None
    status: Optional[ContractStatus] = None
    documents: Optional[Any] = None


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
    margin: Optional[int]  # auto-calculated
    contract_type: ContractType
    status: ContractStatus
    documents: Optional[Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContractList(BaseModel):
    items: list[ContractResponse]
    total: int
    page: int
    page_size: int
