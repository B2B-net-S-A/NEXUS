"""Schemas dla "Moi klienci" + dashboard analityki klienta."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class MyClientRow(BaseModel):
    """Pojedynczy wpis na liście "Moi klienci".

    Pola revenue są ``None`` bez ``VIEW_FINANCE`` (w szczególności dla DL/HoR).
    """

    client_id: int
    name: str
    industry: Optional[str] = None
    is_head_dl: bool = False
    active_orders_count: int = 0
    total_revenue_all_time: Decimal | int | None = None
    active_revenue: Decimal | int | None = None
    expiring_soon_count: int = 0
    framework_contract_status: Optional[str] = None
    framework_expiry_date: Optional[date] = None
    last_activity_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class ExpiringAlert(BaseModel):
    kind: str
    """``framework_contract`` lub ``order``."""

    entity_id: int
    label: str
    days_to_expiry: int
    expiry_date: date


class ClientDashboardResponse(BaseModel):
    """GET `/api/my-clients/{client_id}/dashboard` — analityka klienta.

    Revenue/margin są ``None`` bez ``VIEW_FINANCE`` i router pomija je w JSON.
    """

    client_id: int
    client_name: str

    # Revenue
    total_revenue_all_time: Decimal | int | None = None
    active_revenue: Decimal | int | None = None
    completed_revenue: Decimal | int | None = None
    currency_breakdown: Optional[dict[str, Decimal | int]] = None

    # Margin (auto z linkowanych Contract)
    monthly_margin_total: Optional[int] = None
    monthly_margin_pct: Optional[float] = None

    # Konsultanci
    active_consultants: int = 0
    completed_consultants: int = 0

    # Order velocity
    avg_days_to_fill: Optional[float] = None
    """Średni czas (dni) od `created_at` do gdy `linked_contracts_count == positions_count`."""

    # Counts
    framework_contracts_count: int = 0
    active_orders_count: int = 0
    completed_orders_count: int = 0

    # Alerts (30/14/7 dni do expiry)
    alerts: list[ExpiringAlert] = []
