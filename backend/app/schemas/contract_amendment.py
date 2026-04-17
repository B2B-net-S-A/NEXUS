from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.models.contract_amendment import ContractAmendmentType


class ContractAmendmentCreate(BaseModel):
    amendment_type: ContractAmendmentType
    effective_date: date
    reason: Optional[str] = None
    document_id: Optional[int] = None

    # Target fields — only the ones relevant for the given amendment_type
    # will be applied to the contract. Everything else is captured in
    # old_values / new_values for audit.
    new_end_date: Optional[date] = None
    new_rate_candidate: Optional[int] = None
    new_rate_client: Optional[int] = None
    new_rate_unit: Optional[str] = None
    new_billing_hours_per_month: Optional[int] = None
    new_project_name: Optional[str] = None
    new_team_name: Optional[str] = None


class ContractAmendmentResponse(BaseModel):
    id: int
    contract_id: int
    amendment_type: ContractAmendmentType
    old_values: Optional[Any] = None
    new_values: Optional[Any] = None
    effective_date: date
    reason: Optional[str] = None
    document_id: Optional[int] = None
    created_by: Optional[int] = None
    created_by_email: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}
