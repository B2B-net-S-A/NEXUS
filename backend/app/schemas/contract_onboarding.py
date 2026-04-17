from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel

from app.models.contract_onboarding import OnboardingItemStatus


class OnboardingItemCreate(BaseModel):
    label: str
    status: OnboardingItemStatus = OnboardingItemStatus.pending
    assigned_to: Optional[int] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    order: int = 0


class OnboardingItemUpdate(BaseModel):
    label: Optional[str] = None
    status: Optional[OnboardingItemStatus] = None
    assigned_to: Optional[int] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    order: Optional[int] = None


class OnboardingItemResponse(BaseModel):
    id: int
    contract_id: int
    label: str
    status: OnboardingItemStatus
    assigned_to: Optional[int] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
