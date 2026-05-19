"""Pydantic schemas dla DynaReporter Rada Nadzorcza (Board) dashboard.

Port `/board` z artur-t-96/InfraReporter
(`server/src/routes/boardMonthly.ts` + `client/src/pages/Board.tsx`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class BoardPlacementClient(BaseModel):
    """Pojedynczy klient z placementami w miesiącu."""

    model_config = ConfigDict(from_attributes=True)

    client_name: str
    count: int


class BoardMonthlyRow(BaseModel):
    """Miesięczny raport Rady Nadzorczej."""

    model_config = ConfigDict(from_attributes=True)

    report_month: str = Field(description="YYYY-MM")
    revenue: float = 0.0
    consultant_costs: float = 0.0
    other_costs: float = 0.0
    margin: float = Field(description="revenue - consultant_costs")
    profit: float = Field(description="revenue - consultant_costs - other_costs")
    active_consultants: int = 0
    departures: int = 0
    placements: int = 0
    avg_margin_per_hour: float = 0.0
    hit_ratio: float = 0.0
    placement_clients: list[BoardPlacementClient] = Field(default_factory=list)
