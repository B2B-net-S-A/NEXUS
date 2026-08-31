"""Schemas dla `ClientOrder` (zamówienie od klienta pod kandydackim Contract)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from app.models.client_order import ClientOrderStatus
from app.models.contract import RateUnit
from app.models.order_type import OrderType


class ClientOrderCreate(BaseModel):
    """POST `/api/clients/{client_id}/orders` — Flow A "Dodaj przedłużenie".

    Tworzy Order pod istniejącym kandydackim Contractem.
    """

    contract_id: int  # Required: każdy Order pod konkretnym Contract
    order_type: OrderType = OrderType.periodic
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    status: ClientOrderStatus = ClientOrderStatus.draft
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    rate_candidate: Optional[Decimal] = Field(
        None, ge=0, max_digits=12, decimal_places=3
    )
    rate_client: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=3)
    """Może być różny od Contract.rate_client (przedłużenie z podwyżką)."""
    rate_unit: Optional[RateUnit] = None
    billing_hours_per_month: Optional[int] = Field(None, ge=1)
    total_value: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=2)
    currency: Optional[str] = Field(None, max_length=3)
    rate_client_currency: Optional[str] = Field(None, max_length=3)
    rate_candidate_currency: Optional[str] = Field(None, max_length=3)
    framework_contract_id: Optional[int] = None
    job_id: Optional[int] = None
    notes: Optional[str] = None


class ClientOrderUpdate(BaseModel):
    """PATCH metadata orderu — plik wymaga osobnego PUT `/file`."""

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    order_type: Optional[OrderType] = None
    description: Optional[str] = None
    status: Optional[ClientOrderStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    # Obie stawki są snapshotem tego zamówienia. Contract jest źródłem wartości
    # domyślnej przy tworzeniu, ale ręczna korekta nie może przepisać historii
    # ani sąsiedniego zamówienia tej samej osoby.
    rate_candidate: Optional[Decimal] = Field(
        None, ge=0, max_digits=12, decimal_places=3
    )
    rate_client: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=3)
    rate_unit: Optional[RateUnit] = None
    billing_hours_per_month: Optional[int] = Field(None, ge=1)
    total_value: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=2)
    currency: Optional[str] = Field(None, max_length=3)
    rate_client_currency: Optional[str] = Field(None, max_length=3)
    rate_candidate_currency: Optional[str] = Field(None, max_length=3)
    framework_contract_id: Optional[int] = None
    job_id: Optional[int] = None
    notes: Optional[str] = None
    # „Część umowy" — tylko Centrum e-Zdrowia (walidacja w endpointach przez
    # app/services/ezdrowie.py; słownik cz1|cz2|cz4|cz5|cz6, cz.3 nie istnieje).
    project_part: Optional[str] = Field(None, max_length=8)
    # „Liczba MD zamówienia" (Ticket 2) — tylko klienci wielo-konsultantowi
    # bez zamówień kosztowych; walidacja w handlerze (_apply_md_order_quantity).
    # Opcjonalna: nie należy do czterech pól wymaganych do aktywacji. NULL
    # z jawnym kluczem czyści budżet MD szkicu.
    md_quantity: Optional[Decimal] = Field(None, ge=0, max_digits=16, decimal_places=6)


class ClientOrderRead(BaseModel):
    id: int
    client_id: int
    contract_id: int
    job_id: Optional[int]
    framework_contract_id: Optional[int]
    title: str
    description: Optional[str]
    status: ClientOrderStatus
    order_type: Optional[OrderType] = None
    start_date: Optional[date]
    end_date: Optional[date]
    rate_candidate: Optional[Decimal] = None
    rate_client: Optional[Decimal]
    rate_unit: RateUnit = RateUnit.monthly
    billing_hours_per_month: int = 160
    total_value: Optional[Decimal]
    currency: Optional[str]
    rate_client_currency: Optional[str] = None
    rate_candidate_currency: Optional[str] = None
    # „Część umowy" e-Zdrowia (cz1|cz2|cz4|cz5|cz6) — NULL u innych klientów.
    project_part: Optional[str] = None
    filename: Optional[str]
    has_file: bool
    content_type: Optional[str]
    size_bytes: Optional[int]
    created_by_user_id: Optional[int]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    # Computed (z join'a Contract → Candidate + Job):
    candidate_id: Optional[int] = None
    candidate_name: Optional[str] = None
    contract_status: Optional[str] = None
    job_title: Optional[str] = None
    monthly_margin: Optional[Decimal] = None
    """rate_client (z Order) - rate_candidate (z Contract), normalizowane do mc."""
    days_to_end: Optional[int] = None
    md_quantity: Optional[Decimal] = None
    """Budżet MD wpisany na szkicu przed utworzeniem wspólnej grupy."""

    model_config = {"from_attributes": True}


class ContractWithOrdersRead(BaseModel):
    """Wynik `GET /api/clients/{client_id}/orders` — grupowane po Contract.

    Każdy wiersz = jeden kontraktor (Contract), pod nim historia Orderów (timeline).
    """

    contract_id: int
    candidate_id: int
    candidate_name: str
    contract_status: str
    contract_start_date: Optional[date]
    contract_end_date: Optional[date]
    rate_candidate: Optional[Decimal]  # we płacimy
    rate_client_currency: Optional[str] = None
    rate_candidate_currency: Optional[str] = None
    # Jednostka stawek kontraktu ("hourly" | "daily" | "monthly") — surowe
    # rate_candidate/rate_client są w TEJ jednostce; FE etykietuje /h, /dzień,
    # /mc zamiast hardkodować "/mc". Sama jednostka nie jest kwotą → nie
    # podlega redakcji finansowej.
    rate_unit: str = "monthly"
    billing_hours_per_month: int = 160

    # Initial Job z którego powstał Contract
    initial_job_id: Optional[int]
    initial_job_title: Optional[str]

    # Pozycja na obecnym kontrakcie (z Order najnowszego)
    latest_order_id: Optional[int] = None
    latest_order_end_date: Optional[date] = None
    latest_order_rate_client: Optional[Decimal] = None
    latest_order_monthly_margin: Optional[Decimal] = None
    days_to_latest_end: Optional[int] = None

    orders: list[ClientOrderRead] = []


class ClientOrdersGroupedResponse(BaseModel):
    """`GET /api/clients/{client_id}/orders` response."""

    contractors: list[ContractWithOrdersRead]
    total_contractors: int
    # Czy TEN użytkownik może oglądać i zapisywać kwoty na zamówieniach TEGO
    # klienta (admin albo przypisany Delivery Lead). Front nie zna przypisań
    # DL, więc bez tej flagi renderowałby pola stawek każdemu, kto widzi
    # zakładkę — a zapis kończyłby się 403, co czyta się jak „zapis nie
    # działa", nie jak „nie masz uprawnień".
    can_manage_finance: bool = False


class ClientOrderExportItem(BaseModel):
    """One ordered item in the unified client-order list."""

    kind: Literal["group", "order"]
    id: int = Field(gt=0)


class ClientOrderExportRequest(BaseModel):
    """Legacy order IDs or the ordered items from the unified client view."""

    order_ids: list[int] = Field(default_factory=list, max_length=5000)
    # Pusta wspólna lista jest poprawna: profil może zawierać kartę kontraktu
    # bez żadnego zamówienia. Eksport zwraca wtedy arkusz z samym nagłówkiem,
    # tak jak historyczny kontrakt `order_ids=[]`.
    items: Optional[list[ClientOrderExportItem]] = Field(None, max_length=5000)

    @model_validator(mode="after")
    def _one_ordered_source_without_duplicates(self) -> "ClientOrderExportRequest":
        if self.items is not None and self.order_ids:
            raise ValueError("Podaj order_ids albo items, nie oba pola")
        if self.items is not None:
            keys = [(item.kind, item.id) for item in self.items]
            if len(keys) != len(set(keys)):
                raise ValueError("Lista eksportu zawiera powtórzone zamówienia")
        return self


class OrderExtractionResult(BaseModel):
    """`POST /api/clients/{client_id}/orders/extract` — odczyt pól z PDF/DOCX.

    "Zczytaj dane z dokumentu" w przedłużeniu. NIE tworzy Orderu ani nie zapisuje
    pliku — zwraca odczytane pola do wstawienia w formularzu (wszystkie edytowalne).
    Kwoty (rate_client/total_value/currency) są zredagowane dla ról bez VIEW_FINANCE.
    """

    title: Optional[str] = None
    # Daty jako ISO "YYYY-MM-DD" — front (dateInput) przyjmuje je wprost.
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    rate_client: Optional[Decimal] = None
    rate_unit: Optional[str] = None  # "hour" | "day" | "month"
    rate_client_md: Optional[Decimal] = None
    """Oryginalna stawka za 1 MD z dokumentu (polityka Banku Pocztowego) —
    ``rate_client`` niesie wtedy stawkę GODZINOWĄ po przeliczeniu (MD ÷ 8,
    w górę do 2 miejsc). Front pokazuje obie wartości obok siebie. Kwota
    finansowa: redagowana dla ról bez VIEW_FINANCE tak samo jak stawka."""

    rate_client_gross: Optional[Decimal] = None
    """Oryginalna kwota BRUTTO z dokumentu (polityka Erste Bank Polska) —
    ``rate_client`` niesie wtedy kwotę NETTO po przeliczeniu (÷ 1,23, do 2
    miejsc). Front pokazuje obie obok siebie, żeby dało się skonfrontować
    zapisaną stawkę z PDF-em. Kwota finansowa: redagowana jak stawka."""

    total_value: Optional[Decimal] = None
    currency: Optional[str] = None
    md_total: Optional[Decimal] = None
    """Liczba MD z dokumentu. NIE podlega redakcji finansowej — MD są
    wielkością operacyjną (reguła z ``CLAUDE.md``), a to Delivery Lead ma je
    wpisać do formularza. Ukrycie ich zostawiłoby go z pustym polem tam, gdzie
    ma coś uzupełnić."""

    consultant_ref: Optional[str] = None
    """Numer ID konsultanta odczytany z dokumentu (polityka BNP) — w PDF-ach
    tego klienta nie ma imienia i nazwiska, jest wyłącznie ten numer. Nexus
    nie przechowuje identyfikatorów nadanych przez klienta, więc pole służy
    operatorowi do wzrokowego potwierdzenia, że dokument dotyczy osoby, z
    której karty uruchomił odczyt. Nie jest kwotą — przeżywa redakcję
    finansową, tak samo jak ``title_needs_review``."""

    uncertain: bool = True
    uncertain_reasons: list[str] = Field(default_factory=list)
    fields_confidence: dict[str, float] = Field(default_factory=dict)
    title_needs_review: bool = False
    """Klientowa polityka numeru nie znalazła numeru w dokumencie — front
    pokazuje przy polu numeru komunikat „Sprawdź numer zamówienia". Osobna
    flaga (nie string w ``uncertain_reasons``), bo lista powodów jest
    redagowana dla ról bez VIEW_FINANCE, a numer kwotą nie jest."""

    source: str = "none"  # "claude" | "regex" | "none"


class OrderDocumentItem(BaseModel):
    """Pozycja „Dokumentu zamówienia" — plik PO z ``ClientOrder`` widziany read-only
    w zakładce Dokumenty (kontrakt) oraz w Plikach osoby. Jeden fizyczny plik,
    pobierany istniejącym endpointem ``GET /orders/{order_id}/file``."""

    order_id: int
    client_id: int
    contract_id: int
    title: str
    filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    created_at: datetime
    order_status: ClientOrderStatus
    # Atrybucja wgrania — sekcja „Dokumenty zamówień" pokazuje ją w tym samym
    # miejscu co główna tabela dokumentów kontraktu (`uploaded_by_email` pod
    # datą), żeby wiersz czytał się jak każdy inny dokument kontraktu.
    # NULL dla plików wgranych przed migracją 0227, która dodała te kolumny.
    uploaded_by_email: Optional[str] = None
    uploaded_at: Optional[datetime] = None


class OrderDocumentsResponse(BaseModel):
    documents: list[OrderDocumentItem]
