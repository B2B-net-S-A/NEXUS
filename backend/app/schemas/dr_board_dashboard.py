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


class BoardMonthlyUpsert(BaseModel):
    """Payload POST /monthly — admin upsert miesięcznego raportu."""

    model_config = ConfigDict(from_attributes=True)

    # Format enforced — bez `pattern=` admin może wpisać "2026-13" lub "abc"
    # i dostanie raw PostgreSQL 500 (DataError on date cast).
    report_month: str = Field(
        description="YYYY-MM",
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
    )
    # `ge=0` na wszystkich liczbach — admin nie powinien wpisać ujemnego revenue.
    # `le=100.0` na hit_ratio bo to procent.
    revenue: float = Field(default=0.0, ge=0)
    consultant_costs: float = Field(default=0.0, ge=0)
    other_costs: float = Field(default=0.0, ge=0)
    active_consultants: int = Field(default=0, ge=0)
    departures: int = Field(default=0, ge=0)
    placements: int = Field(default=0, ge=0)
    avg_margin_per_hour: float = Field(default=0.0, ge=0)
    hit_ratio: float = Field(default=0.0, ge=0, le=100.0)
    placement_clients: list[BoardPlacementClient] = Field(default_factory=list)
