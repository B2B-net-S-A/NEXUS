"""Pydantic schemas dla DynaReporter Delivery Lead dashboard.

Port `/delivery-lead` z artur-t-96/InfraReporter
(`server/src/routes/deliveryLead.ts` + `client/src/pages/DeliveryLead.tsx`).

2026-07-20: usunięty `DLUpsert` — był payloadem wyłącznie usuniętej trasy
POST /entry (ręczne wprowadzanie statystyk wygaszone).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class DLMember(BaseModel):
    """Pojedynczy Delivery Lead z agregatami."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool = True
    requests: int = 0
    placements: int = 0
    vacancies: int = 0
    open_requests: int = 0
    open_vacancies: int = 0
    hit_ratio: float = Field(description="placements/requests × 100 (target 30%)")
    fill_rate: float = Field(description="placements/vacancies × 100")
    avg_vacancies_per_request: float
    hit_ratio_target: int = 30
    target_achieved: bool
    rank: int


class DLTeamStats(BaseModel):
    """Team-wide DL aggregates."""

    model_config = ConfigDict(from_attributes=True)

    total_requests: int = 0
    total_placements: int = 0
    total_vacancies: int = 0
    total_open_requests: int = 0
    total_open_vacancies: int = 0
    average_hit_ratio: float = 0.0
    average_fill_rate: float = 0.0
    achieving_target: int = 0
    active_dls_count: int = Field(
        default=0,
        description="Liczba DLs które mają realne dane (filtruje duplikaty z "
        "DR migracji). Denominator dla `achieving_target` w UI.",
    )


class DLTeamHistoryRow(BaseModel):
    """Miesiąc w historii zespołu (12 mies. trend)."""

    model_config = ConfigDict(from_attributes=True)

    month: str = Field(description="YYYY-MM-DD pierwszy dzień miesiąca")
    requests: int = 0
    vacancies: int = 0
    placements: int = 0
    hit_ratio: float = 0.0
    fill_rate: float = 0.0


class DLTrendRow(BaseModel):
    """Trend hit-ratio per użytkownik (ostatnie N miesięcy)."""

    model_config = ConfigDict(from_attributes=True)

    month: str
    requests: int = 0
    placements: int = 0
    hit_ratio: float = 0.0


class DLDashboard(BaseModel):
    """Pełen payload `/dashboard` endpointu."""

    model_config = ConfigDict(from_attributes=True)

    delivery_leads: list[DLMember]
    team_stats: DLTeamStats
    team_history: list[DLTeamHistoryRow]
    hit_ratio_target: int = 30
    period_label: str
    period_start: Optional[date] = None
    period_end: Optional[date] = None
