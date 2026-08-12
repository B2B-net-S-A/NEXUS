"""Schemas dla `/api/admin/clients-overview` (przekrojowe widoki)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.schemas.money import WholePLN


class OverviewRow(BaseModel):
    """Wiersz w rankingu klientów."""

    client_id: int
    name: str
    industry: Optional[str] = None
    head_dl_id: Optional[int] = None
    head_dl_name: Optional[str] = None
    total_revenue_all_time: Decimal | int | None = None
    active_revenue: Decimal | int | None = None
    monthly_margin_total: Optional[WholePLN] = None
    active_orders_count: int = 0
    active_consultants: int = 0
    framework_status: Optional[str] = None
    framework_expiry_date: Optional[date] = None

    model_config = {"from_attributes": True}


class DlKpiRow(BaseModel):
    """Wiersz w leaderboardzie DL."""

    dl_user_id: int
    dl_name: str
    dl_email: str
    managed_clients_count: int = 0
    head_clients_count: int = 0
    total_revenue: Decimal | int | None = None
    active_revenue: Decimal | int | None = None
    monthly_margin_total: Optional[WholePLN] = None
    active_orders_count: int = 0
    active_consultants: int = 0
