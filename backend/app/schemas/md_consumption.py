"""DTO importu zużycia MD (moduł Finanse)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, Field, PlainSerializer

from app.services.multi_consultant_orders import MD_SCALE


def _md_out(value: Decimal) -> float:
    return float(Decimal(value).quantize(MD_SCALE))


MdValue = Annotated[
    Decimal, PlainSerializer(_md_out, return_type=float, when_used="json")
]


class LineOption(BaseModel):
    """Linia do wyboru przy wierszu „wymaga przypisania".

    Projekcja jest WĄSKA celowo: numer zamówienia, klient i konsultant — tyle,
    ile trzeba, żeby wskazać właściwe zamówienie. Bez identyfikatora kandydata,
    kontraktu i stawek, bo moduł Finanse nie jest powierzchnią kandydacką.
    """

    order_id: int
    order_number: str
    client_id: int
    client_name: str
    consultant_name: str
    md_remaining: Optional[MdValue] = None


class ImportRowRead(BaseModel):
    id: int
    row_number: int
    consultant_name: str
    md_reported: MdValue
    status: str
    status_label: str
    matched_order_id: Optional[int] = None
    matched: Optional[LineOption] = None
    options: list[LineOption] = Field(default_factory=list)
    resolved_at: Optional[datetime] = None


class ImportSummary(BaseModel):
    id: int
    period_month: str
    filename: Optional[str] = None
    rows_total: int = 0
    rows_applied: int = 0
    rows_ambiguous: int = 0
    rows_unmatched: int = 0
    uploaded_by_user_id: Optional[int] = None
    created_at: datetime


class ImportDetail(ImportSummary):
    rows: list[ImportRowRead] = Field(default_factory=list)
    skipped_rows: list[dict] = Field(default_factory=list)
    sheet_name: Optional[str] = None


class ImportListResponse(BaseModel):
    imports: list[ImportSummary] = Field(default_factory=list)


class AssignRowRequest(BaseModel):
    order_id: int
