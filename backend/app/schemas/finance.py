"""Schematy modułu „Finanse" — miesięczne wyniki kontraktorów.

Kwoty jadą na drut jako JSON-owe LICZBY, nie stringi. Pydantic serializuje gołe
``Decimal`` jako string, co front cicho skleja zamiast dodawać (``acc + row.x``)
— ten sam trap co w ``contract_analytics.MoneyPLN``, powtórzony tutaj zamiast
importowany, żeby moduł finansowy nie zależał od modułu analityki kontraktów.

W ŻADNYM schemacie odpowiedzi nie ma sześciu kolumn arkusza spoza tabeli
wynikowej (Uwagi, Projekt, Stawka z VD, Czy wystawiono fakturę, Data wysłania,
Płatny urlop). Nie są też zapisywane w bazie — ticket wymaga, żeby żyły
wyłącznie w oryginalnym pliku dostępnym z Archiwum.
"""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Optional

from pydantic import BaseModel, Field, PlainSerializer

MoneyPLN = Annotated[
    Decimal,
    PlainSerializer(
        lambda v: float(Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        return_type=float,
        when_used="json",
    ),
]

# Pola liczbowe, które operator może poprawić ręcznie w tabeli. Lustro
# ``finance_import.NUMERIC_FIELDS``; pilnuje go test kontraktowy.
EDITABLE_NUMERIC_FIELDS: tuple[str, ...] = (
    "cost_rate_md",
    "md_count",
    "compensation",
    "revenue_rate_md",
    "invoice_amount",
    "margin_pln",
    "margin_pct",
)


class FinancePeriod(BaseModel):
    """Pozycja selektora miesiąca — wyłącznie okresy, które mają import."""

    year: int
    month: int
    label: str  # „Sierpień 2026"
    run_id: int
    row_count: int


class FinanceResultRow(BaseModel):
    id: int
    row_number: int
    consultant_name: str
    client_name: Optional[str] = None
    cost_rate_md: Optional[MoneyPLN] = None
    md_count: Optional[MoneyPLN] = None
    compensation: Optional[MoneyPLN] = None
    revenue_rate_md: Optional[MoneyPLN] = None
    invoice_amount: Optional[MoneyPLN] = None
    margin_pln: Optional[MoneyPLN] = None
    margin_pct: Optional[MoneyPLN] = None
    # Pola zmienione RĘCZNIE po imporcie. Front używa tego, żeby odróżnić
    # „pusto, bo import nie dał wartości" (ramka „Uzupełnij") od „pusto, bo
    # człowiek świadomie wyczyścił" — te drugie nie wołają o uzupełnienie.
    edited_fields: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class FinanceTotals(BaseModel):
    """Kafle. Liczone SERWEROWO z tych samych wierszy, które zwraca `/results`.

    Kafel będący sumą innych liczb niż widoczne pod nim jest niemożliwy do
    zweryfikowania wzrokiem — dlatego nie ma tu osobnego zapytania agregującego.
    """

    cost: MoneyPLN  # Σ „Wynagrodzenie"
    revenue: MoneyPLN  # Σ „Faktura"
    margin: MoneyPLN  # Σ „Marża PLN"
    avg_margin_pct: Optional[MoneyPLN] = None


class FinanceResultsResponse(BaseModel):
    year: int
    month: int
    run_id: int
    rows: list[FinanceResultRow]
    totals: FinanceTotals
    needs_completion_count: int


class FinanceRowUpdate(BaseModel):
    """PATCH pojedynczej komórki. Pola rozróżniane po ``model_fields_set``,
    więc pominięcie pola zostawia je bez zmian, a jawne ``null`` czyści."""

    cost_rate_md: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=2)
    md_count: Optional[Decimal] = Field(None, ge=0, max_digits=8, decimal_places=2)
    compensation: Optional[Decimal] = Field(None, max_digits=14, decimal_places=2)
    revenue_rate_md: Optional[Decimal] = Field(
        None, ge=0, max_digits=12, decimal_places=2
    )
    invoice_amount: Optional[Decimal] = Field(None, max_digits=14, decimal_places=2)
    # Marża bywa ujemna — brak `ge=0` jest tu świadomy.
    margin_pln: Optional[Decimal] = Field(None, max_digits=14, decimal_places=2)
    margin_pct: Optional[Decimal] = Field(None, max_digits=7, decimal_places=2)


class FinanceImportRunRead(BaseModel):
    """Wiersz Archiwum."""

    id: int
    year: int
    month: int
    label: str
    status: str  # "current" | "superseded"
    source_filename: str
    size_bytes: Optional[int] = None
    row_count: int
    needs_completion_count: int
    rejected_count: int
    created_at: datetime
    superseded_at: Optional[datetime] = None
    created_by_email: Optional[str] = None


class FinanceImportRejection(BaseModel):
    row_number: int
    reason: str


class FinanceImportResult(BaseModel):
    """Podsumowanie udanego importu (panel po wgraniu pliku)."""

    run_id: int
    year: int
    month: int
    imported: int
    needs_completion: int
    rejected: int
    rejections: list[FinanceImportRejection] = Field(default_factory=list)
    replaced_run_id: Optional[int] = None


class FinancePeriodConflict(BaseModel):
    """Ciało 409 z `POST /imports` przy istniejącej wersji miesiąca.

    Front zamienia to na pytanie „Zastąpić?" z KONKRETNYMI liczbami — w tym
    liczbą wierszy niosących ręczne poprawki, które przepadną. Ostrzeżenie bez
    tej liczby nie pozwala ocenić, ile pracy się traci.
    """

    code: str = "period_exists"
    run_id: int
    year: int
    month: int
    row_count: int
    edited_row_count: int


class FinanceHeaderMismatch(BaseModel):
    """Ciało 422 przy złych nagłówkach — import odrzucony w całości."""

    code: str = "invalid_headers"
    missing: list[str]
    unexpected: list[str]
