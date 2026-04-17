from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.models.contract import RateUnit


class RateCardBase(BaseModel):
    role: str
    seniority: Optional[str] = None
    rate_candidate_min: Optional[int] = None
    rate_candidate_max: Optional[int] = None
    rate_client_min: Optional[int] = None
    rate_client_max: Optional[int] = None
    currency: str = "PLN"
    rate_unit: RateUnit = RateUnit.monthly
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    notes: Optional[str] = None


class RateCardCreate(RateCardBase):
    client_id: int


class RateCardUpdate(BaseModel):
    role: Optional[str] = None
    seniority: Optional[str] = None
    rate_candidate_min: Optional[int] = None
    rate_candidate_max: Optional[int] = None
    rate_client_min: Optional[int] = None
    rate_client_max: Optional[int] = None
    currency: Optional[str] = None
    rate_unit: Optional[RateUnit] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    notes: Optional[str] = None


class RateCardResponse(RateCardBase):
    id: int
    client_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RateCardSuggestion(BaseModel):
    """Lightweight response for contract-form auto-suggest."""

    matched: bool
    rate_card_id: Optional[int] = None
    rate_candidate_suggestion: Optional[int] = None
    rate_client_suggestion: Optional[int] = None
    currency: Optional[str] = None
    rate_unit: Optional[RateUnit] = None
    source_role: Optional[str] = None
    source_seniority: Optional[str] = None
