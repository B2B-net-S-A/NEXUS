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


def _money_out(value: Decimal) -> float:
    return float(Decimal(value).quantize(Decimal("0.001")))


# Liczba, nie string — front rysuje z tego pasek budżetu i porównuje kwoty.
MoneyValue = Annotated[
    Decimal, PlainSerializer(_money_out, return_type=float, when_used="json")
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

    # ── Rozliczenie kosztowe (Polkomtel) ──
    # `cost_status is None` znaczy „wiersz nie dotyczy zamówień kosztowych",
    # a nie „nie udało się dopasować" — front musi te dwa stany rozróżniać,
    # inaczej każdy wiersz zwykłego arkusza MD zapaliłby się na czerwono.
    notes_raw: Optional[str] = None
    order_number_hint: Optional[str] = None
    invoice_amount: Optional[MoneyValue] = None
    cost_status: Optional[str] = None
    cost_status_label: Optional[str] = None


class ImportSummary(BaseModel):
    id: int
    period_month: str
    filename: Optional[str] = None
    rows_total: int = 0
    rows_applied: int = 0
    rows_ambiguous: int = 0
    rows_unmatched: int = 0
    rows_cost_applied: int = 0
    rows_cost_unmatched: int = 0
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


class PolkomtelReprocessRequest(BaseModel):
    """Dry-run by default; ``apply=true`` performs the reviewed correction."""

    apply: bool = False


class PolkomtelReprocessTarget(BaseModel):
    kind: str
    order_id: Optional[int] = None
    group_id: int
    order_number: str
    # Wszystkie wiersze składające się na oczekiwaną wartość oraz ich podzbiór,
    # którego status/dopasowanie rzeczywiście zostanie poprawione przez APPLY.
    row_ids: list[int] = Field(default_factory=list)
    row_ids_to_update: list[int] = Field(default_factory=list)
    current_value: Optional[Decimal] = None
    expected_value: Decimal
    write_required: bool


class PolkomtelReprocessResponse(BaseModel):
    import_id: int
    period_month: str
    client_id: int
    applied: bool
    rows_scanned: int
    rows_to_update: int
    targets_to_recalculate: int
    conflicts: list[str] = Field(default_factory=list)
    targets: list[PolkomtelReprocessTarget] = Field(default_factory=list)
