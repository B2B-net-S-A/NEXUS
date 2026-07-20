"""Pydantic schemas for DynaReporter Sales KPI (B.2.2).

2026-07-20: usunięty `DrKpiSalesCreate` — był payloadem wyłącznie usuniętej
trasy POST (ręczne wprowadzanie statystyk wygaszone).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DrKpiSalesBase(BaseModel):
    report_date: date
    week_number: int = Field(ge=1, le=53)
    leads: int = Field(default=0, ge=0)
    offers_sent: int = Field(default=0, ge=0)
    offers_won: int = Field(default=0, ge=0)
    offers_lost: int = Field(default=0, ge=0)
    days_worked: int = Field(default=5, ge=0, le=7)


class DrKpiSalesResponse(DrKpiSalesBase):
    id: int
    user_id: int
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class DrKpiSalesSummary(BaseModel):
    period: str
    from_date: date
    to_date: date
    total_leads: int
    total_offers_sent: int
    total_offers_won: int
    total_offers_lost: int
    total_days_worked: int
    entries_count: int
    win_rate: float = Field(description="offers_won / (offers_won + offers_lost)")
