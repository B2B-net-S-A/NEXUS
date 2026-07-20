"""Pydantic schemas dla DynaReporter KPI Delivery Lead (B.2.3).

2026-07-20: usunięty `DrKpiDeliveryLeadCreate` — był payloadem wyłącznie
usuniętej trasy POST (ręczne wprowadzanie statystyk wygaszone).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DrKpiDeliveryLeadBase(BaseModel):
    report_month: date = Field(description="Pierwszy dzień miesiąca (YYYY-MM-01)")
    requests: int = Field(default=0, ge=0)
    placements: int = Field(default=0, ge=0)
    vacancies: int = Field(default=0, ge=0)
    open_requests: int = Field(default=0, ge=0)
    open_vacancies: int = Field(default=0, ge=0)


class DrKpiDeliveryLeadResponse(DrKpiDeliveryLeadBase):
    id: int
    user_id: int
    user_name: Optional[str] = None
    user_email: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class DrKpiDeliveryLeadSummary(BaseModel):
    months_count: int
    total_requests: int
    total_placements: int
    total_vacancies: int
    avg_open_requests: float
    avg_open_vacancies: float
    fill_rate: float = Field(description="placements / requests")
