"""Schemas dla `ClientOrder` (zamówienie od klienta pod kandydackim Contract)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.client_order import ClientOrderStatus


class ClientOrderCreate(BaseModel):
    """POST `/api/clients/{client_id}/orders` — Flow A "Dodaj przedłużenie".

    Tworzy Order pod istniejącym kandydackim Contractem.
    """

    contract_id: int  # Required: każdy Order pod konkretnym Contract
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    status: ClientOrderStatus = ClientOrderStatus.draft
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    rate_client: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=3)
    """Może być różny od Contract.rate_client (przedłużenie z podwyżką)."""
    total_value: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=2)
    currency: Optional[str] = Field(None, max_length=3)
    framework_contract_id: Optional[int] = None
    job_id: Optional[int] = None
    notes: Optional[str] = None


class ClientOrderUpdate(BaseModel):
    """PATCH metadata orderu — plik wymaga osobnego PUT `/file`."""

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[ClientOrderStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    # Stawka KOSZTOWA mieszka na powiązanym ``Contract``, nie na zamówieniu —
    # przyjmujemy ją tutaj, bo formularz uzupełnienia draftu pokazuje obie
    # stawki obok siebie i zapisuje je jednym żądaniem. Handler przepisuje ją
    # na kontrakt; `PATCH /api/contracts/{id}` zostaje nietknięty (ma własną,
    # admin-only bramkę osłaniającą 17 pól i ~20 innych odpowiedzi).
    rate_candidate: Optional[Decimal] = Field(
        None, ge=0, max_digits=12, decimal_places=3
    )
    rate_client: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=3)
    total_value: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=2)
    currency: Optional[str] = Field(None, max_length=3)
    framework_contract_id: Optional[int] = None
    job_id: Optional[int] = None
    notes: Optional[str] = None
    # „Część umowy" — tylko Centrum e-Zdrowia (walidacja w endpointach przez
    # app/services/ezdrowie.py; słownik cz1|cz2|cz4|cz5|cz6, cz.3 nie istnieje).
    project_part: Optional[str] = Field(None, max_length=8)


class ClientOrderRead(BaseModel):
    id: int
    client_id: int
    contract_id: int
    job_id: Optional[int]
    framework_contract_id: Optional[int]
    title: str
    description: Optional[str]
    status: ClientOrderStatus
    start_date: Optional[date]
    end_date: Optional[date]
    rate_client: Optional[Decimal]
    total_value: Optional[Decimal]
    currency: Optional[str]
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
    # Jednostka stawek kontraktu ("hourly" | "daily" | "monthly") — surowe
    # rate_candidate/rate_client są w TEJ jednostce; FE etykietuje /h, /dzień,
    # /mc zamiast hardkodować "/mc". Sama jednostka nie jest kwotą → nie
    # podlega redakcji finansowej.
    rate_unit: str = "monthly"

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


class ClientOrderExportRequest(BaseModel):
    """Ordered IDs currently visible in the client-side list."""

    order_ids: list[int] = Field(default_factory=list, max_length=5000)


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

    total_value: Optional[Decimal] = None
    currency: Optional[str] = None
    md_total: Optional[Decimal] = None
    """Liczba MD z dokumentu. NIE podlega redakcji finansowej — MD są
    wielkością operacyjną (reguła z ``CLAUDE.md``), a to Delivery Lead ma je
    wpisać do formularza. Ukrycie ich zostawiłoby go z pustym polem tam, gdzie
    ma coś uzupełnić."""

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
