"""DTO zamówień wielo-konsultantowych (grupa + linie konsultantów + historia).

Liczby MD i stawki jadą na drut jako **JSON number**, nie string. Goły
``Decimal`` w Pydantic v2 serializuje się do stringa, a front liczy z nich
procent wypełnienia paska zużycia — ``"15" / "50"`` w JS nie jest błędem,
tylko cichym ``NaN``. Ten sam problem rozwiązano wcześniej w
``app/api/invoices.py`` (``MoneyPLN``); tutaj potrzebne są dwie skale, więc
serializery są dwa.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Optional

from pydantic import BaseModel, Field, PlainSerializer, field_validator

from app.services.multi_consultant_orders import (
    INPUT_MODES,
    MD_DISPLAY_SCALE,
    MD_SCALE,
)


def _md_out(value: Decimal) -> float:
    return float(Decimal(value).quantize(MD_SCALE))


def _money_out(value: Decimal) -> float:
    return float(Decimal(value).quantize(MD_DISPLAY_SCALE))


# Pełna precyzja wewnątrz, JSON number na drucie. Zaokrąglenie do 2 miejsc
# robi wyłącznie warstwa prezentacji — patrz docstring
# ``app/services/multi_consultant_orders``.
MdValue = Annotated[
    Decimal, PlainSerializer(_md_out, return_type=float, when_used="json")
]
MoneyPLN = Annotated[
    Decimal, PlainSerializer(_money_out, return_type=float, when_used="json")
]


# ── Wejście ─────────────────────────────────────────────────────────────────


class OrderLineCreate(BaseModel):
    """Jedna linia konsultanta przy zakładaniu zamówienia lub dokładaniu osoby."""

    contract_id: int
    """Kontrakt konsultanta u tego klienta. Linia wskazuje ISTNIEJĄCY kontrakt,
    więc osoba z zamówienia pozostaje widoczna w MRR, rejestrze kontraktów i
    alertach wygasania — nie powstaje druga, równoległa prawda o tym, kto
    u klienta pracuje."""

    rate_cost: MoneyPLN = Field(..., ge=0, max_digits=12, decimal_places=2)
    rate_revenue: MoneyPLN = Field(..., gt=0, max_digits=12, decimal_places=2)
    """Stawka przychodowa jest dzielnikiem (kwota→MD, przeliczenie przy
    zamianie kontraktora), więc zero jest odrzucane już na wejściu."""

    input_mode: str
    input_value: MdValue = Field(..., ge=0, max_digits=16, decimal_places=6)
    start_date: date
    end_date: Optional[date] = None
    job_id: Optional[int] = None

    @field_validator("input_mode")
    @classmethod
    def _mode(cls, v: str) -> str:
        if v not in INPUT_MODES:
            raise ValueError("Tryb budżetu musi być 'md' albo 'amount'")
        return v


class OrderGroupCreate(BaseModel):
    order_number: str = Field(..., min_length=1, max_length=64)
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None
    lines: list[OrderLineCreate] = Field(default_factory=list)


class OrderGroupUpdate(BaseModel):
    order_number: Optional[str] = Field(None, min_length=1, max_length=64)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None


class OrderLineUpdate(BaseModel):
    """Edycja linii. Pola nieprzysłane zostają bez zmian (``exclude_unset``)."""

    rate_cost: Optional[MoneyPLN] = Field(None, ge=0, max_digits=12, decimal_places=2)
    rate_revenue: Optional[MoneyPLN] = Field(
        None, gt=0, max_digits=12, decimal_places=2
    )
    input_mode: Optional[str] = None
    input_value: Optional[MdValue] = Field(None, ge=0, max_digits=16, decimal_places=6)
    end_date: Optional[date] = None
    md_remaining: Optional[MdValue] = Field(None, max_digits=16, decimal_places=6)
    """Ręczna korekta pozostałości (korekta historyczna). Zapisywana jako
    RÓŻNICA w ``md_manual_adjustment``, nie nadpisaniem — inaczej najbliższy
    import miesiąca przeliczyłby pozostałość od ``md_total`` i skasował ją."""

    @field_validator("input_mode")
    @classmethod
    def _mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in INPUT_MODES:
            raise ValueError("Tryb budżetu musi być 'md' albo 'amount'")
        return v


class OrderLineSwapRequest(BaseModel):
    """Zamiana kontraktora na linii."""

    contract_id: int
    rate_cost: MoneyPLN = Field(..., ge=0, max_digits=12, decimal_places=2)
    rate_revenue: MoneyPLN = Field(..., gt=0, max_digits=12, decimal_places=2)
    swap_date: date


# ── Wyjście ─────────────────────────────────────────────────────────────────


class OrderLineRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    group_id: Optional[int] = None
    contract_id: int
    candidate_id: Optional[int] = None
    consultant_name: str = ""
    job_id: Optional[int] = None
    job_title: Optional[str] = None
    status: str
    is_active: bool
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    # Finansowe — zerowane dla ról bez VIEW_FINANCE.
    rate_cost: Optional[MoneyPLN] = None
    rate_revenue: Optional[MoneyPLN] = None
    input_value: Optional[MdValue] = None

    input_mode: Optional[str] = None
    # Liczby MD są operacyjne, nie finansowe — pasek zużycia działa także dla
    # ról bez dostępu do stawek. Ukrycie ich zostawiłoby te role z pustą
    # kolumną bez wyjaśnienia, choć MD nie są kwotą.
    md_total: Optional[MdValue] = None
    md_remaining: Optional[MdValue] = None
    md_manual_adjustment: Optional[MdValue] = None

    predecessor_order_id: Optional[int] = None
    predecessor_consultant_name: Optional[str] = None


class OrderGroupEventRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    event_type: str
    event_label: str
    description: str
    order_id: Optional[int] = None
    payload: Optional[dict[str, Any]] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime


class OrderGroupRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    client_id: int
    order_number: str
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None
    created_at: datetime
    lines: list[OrderLineRead] = Field(default_factory=list)
    active_consultants: int = 0
    event_count: int = 0


class OrderGroupListResponse(BaseModel):
    groups: list[OrderGroupRead] = Field(default_factory=list)
    total_groups: int = 0
    total_consultants: int = 0


class OrderGroupEventsResponse(BaseModel):
    events: list[OrderGroupEventRead] = Field(default_factory=list)


class SwapPreview(BaseModel):
    """Podgląd przeliczenia MD przy zamianie — liczony po stronie serwera."""

    md_remaining_old: MdValue
    remaining_value_pln: Optional[MoneyPLN] = None
    md_total_new: MdValue
