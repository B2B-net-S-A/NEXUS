"""Schematy Finanse → Zamówienia PDF."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel


class OrderPdfMonth(BaseModel):
    month: str  # RRRR-MM
    clients: int
    files: int


class OrderPdfMonthsResponse(BaseModel):
    items: list[OrderPdfMonth]


class OrderPdfFile(BaseModel):
    kind: Literal["order", "group", "amendment"]
    id: int
    download_name: str
    original_name: str
    consultant_name: Optional[str]
    start: date
    end: Optional[date]
    entry_type: Literal["new", "extension", "amendment"]
    status: Optional[str]
    order_number: Optional[str]
    uploaded_at: Optional[datetime]
    # Pobranie przez ZALOGOWANĄ osobę (0354) — ``None`` = „Nowy".
    downloaded_at: Optional[datetime] = None
    # Zamówienie ma w tym miesiącu pozycję „Do zrobienia" w Zmianach.
    pending_change: bool = False


class OrderPdfClient(BaseModel):
    client_id: int
    client_name: str
    files: list[OrderPdfFile]


class OrderPdfsResponse(BaseModel):
    year: int
    month: int
    clients: list[OrderPdfClient]
