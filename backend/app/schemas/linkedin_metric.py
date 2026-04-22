"""Pydantic schemas for LinkedIn daily metrics."""

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


class LinkedInMetricIn(BaseModel):
    user_id: int
    report_date: date
    cv_added: int = Field(0, ge=0)
    messages_sent: int = Field(0, ge=0)
    responses_received: int = Field(0, ge=0)
    notes: Optional[str] = None


class LinkedInMetricOut(LinkedInMetricIn):
    id: int
    name: Optional[str] = None
    week_number: Optional[int] = None

    class Config:
        from_attributes = True


class LinkedInBulkPayload(BaseModel):
    """Bulk upsert — lista wierszy (user × date)."""

    rows: list[LinkedInMetricIn]


class LinkedInUserTotals(BaseModel):
    user_id: int
    name: str
    role: Optional[str] = None
    cv_added: int
    messages_sent: int
    responses_received: int
    response_rate: float  # responses / messages_sent * 100
    cv_response_rate: float  # responses / cv_added * 100 (quality proxy)
    days_reported: int


class LinkedInSummary(BaseModel):
    period: str
    date_from: date
    date_to: date
    per_user: list[LinkedInUserTotals]
    totals: dict
