"""Pydantic schemas for DynaReporter Body Leasing KPI (B.2.1)."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DrKpiBodyLeasingBase(BaseModel):
    """Wspólne pola dla create/update — wszystkie counters."""

    report_date: date = Field(description="Data tygodnia raportowania")
    week_number: int = Field(ge=1, le=53, description="Numer tygodnia ISO")
    verifications: int = Field(default=0, ge=0)
    recommendations: int = Field(default=0, ge=0)
    interviews: int = Field(default=0, ge=0)
    placements: int = Field(default=0, ge=0)
    requests: int = Field(default=0, ge=0)
    days_worked: int = Field(default=5, ge=0, le=7)
    is_draft: bool = Field(default=False)
    linkedin_cv_added: int = Field(default=0, ge=0)
    linkedin_messages_sent: int = Field(default=0, ge=0)
    linkedin_responses_received: int = Field(default=0, ge=0)


class DrKpiBodyLeasingCreate(DrKpiBodyLeasingBase):
    """Body wejściowe dla POST /api/dynareporter/kpi/body-leasing.

    user_id wnoszony z JWT (current_user.id) — user może zapisywać tylko
    swoje wpisy (admin może zapisywać dowolne via ?user_id=X query).
    """


class DrKpiBodyLeasingUpdate(BaseModel):
    """PATCH body — wszystkie pola opcjonalne."""

    verifications: Optional[int] = Field(default=None, ge=0)
    recommendations: Optional[int] = Field(default=None, ge=0)
    interviews: Optional[int] = Field(default=None, ge=0)
    placements: Optional[int] = Field(default=None, ge=0)
    requests: Optional[int] = Field(default=None, ge=0)
    days_worked: Optional[int] = Field(default=None, ge=0, le=7)
    is_draft: Optional[bool] = None
    linkedin_cv_added: Optional[int] = Field(default=None, ge=0)
    linkedin_messages_sent: Optional[int] = Field(default=None, ge=0)
    linkedin_responses_received: Optional[int] = Field(default=None, ge=0)


class DrKpiBodyLeasingResponse(DrKpiBodyLeasingBase):
    """Response shape — base + system fields."""

    id: int
    user_id: int
    user_name: Optional[str] = None  # JOIN result
    user_email: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class DrKpiBodyLeasingSummary(BaseModel):
    """Agregaty period: week/month/quarter/year.

    Zwracane przez GET /api/dynareporter/kpi/body-leasing/summary.
    """

    period: str = Field(description="week, month, quarter, year")
    from_date: date
    to_date: date
    total_verifications: int
    total_recommendations: int
    total_interviews: int
    total_placements: int
    total_requests: int
    total_days_worked: int
    entries_count: int = Field(description="Ilość wierszy w okresie")


class DrKpiBodyLeasingRankingEntry(BaseModel):
    """Jeden wiersz w rankingu placementów per user."""

    user_id: int
    user_name: str
    user_email: str
    total_placements: int
    total_interviews: int
    total_recommendations: int
    total_verifications: int
    rank: int = Field(description="1, 2, 3, ... (sorted by total_placements DESC)")
