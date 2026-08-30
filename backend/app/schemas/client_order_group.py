"""DTO zamówień wielo-konsultantowych (grupa + linie konsultantów + historia).

Liczby MD i stawki jadą na drut jako **JSON number**, nie string. Goły
``Decimal`` w Pydantic v2 serializuje się do stringa, a front liczy z nich
procent wypełnienia paska zużycia — ``"15" / "50"`` w JS nie jest błędem,
tylko cichym ``NaN``. Ten sam problem rozwiązano wcześniej w
``app/api/invoices.py`` (``MoneyPLN``); tutaj potrzebne są osobne skale dla
MD, pieniędzy linii, surowej stawki kontraktu i kursu FX.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional

from pydantic import (
    BaseModel,
    Field,
    PlainSerializer,
    field_validator,
    model_validator,
)

from app.models.contract import RateUnit
from app.models.order_type import OrderType
from app.services.multi_consultant_orders import (
    INPUT_MODES,
    MD_DISPLAY_SCALE,
    MD_SCALE,
)


def _md_out(value: Decimal) -> float:
    return float(Decimal(value).quantize(MD_SCALE))


def _money_out(value: Decimal) -> float:
    return float(Decimal(value).quantize(MD_DISPLAY_SCALE))


def _contract_rate_out(value: Decimal) -> float:
    return float(Decimal(value).quantize(Decimal("0.001")))


# Pełna precyzja wewnątrz, JSON number na drucie. Zaokrąglenie do 2 miejsc
# robi wyłącznie warstwa prezentacji — patrz docstring
# ``app/services/multi_consultant_orders``.
MdValue = Annotated[
    Decimal, PlainSerializer(_md_out, return_type=float, when_used="json")
]
MoneyPLN = Annotated[
    Decimal, PlainSerializer(_money_out, return_type=float, when_used="json")
]
# Stawki kontraktu są Numeric(12,3), więc podpowiedź nie może przechodzić
# przez MoneyPLN (2 miejsca). JSON number zachowuje pełną skalę źródła.
ContractRateValue = Annotated[
    Decimal, PlainSerializer(_contract_rate_out, return_type=float, when_used="json")
]
# Kurs FX jest Numeric(14,6); skala MdValue jest identyczna i nie obcina danych.
FxRateValue = MdValue


# ── Wejście ─────────────────────────────────────────────────────────────────


class OrderLineCreate(BaseModel):
    """Jedna linia konsultanta przy zakładaniu zamówienia lub dokładaniu osoby.

    Osobę wskazuje się DOKŁADNIE JEDNYM z dwóch pól — ``contract_id`` albo
    ``candidate_id``. Dwa pola zamiast jednego, bo linia musi wisieć na
    kontrakcie u tego klienta (``client_orders.contract_id`` jest NOT NULL i
    czyta go kilkanaście ścieżek: skaner wygasania, sync terminacji, MRR),
    a osoba z bazy Nexus takiego kontraktu jeszcze nie ma.
    """

    contract_id: Optional[int] = None
    """Kontrakt konsultanta u tego klienta. Linia wskazuje ISTNIEJĄCY kontrakt,
    więc osoba z zamówienia pozostaje widoczna w MRR, rejestrze kontraktów i
    alertach wygasania — nie powstaje druga, równoległa prawda o tym, kto
    u klienta pracuje."""

    candidate_id: Optional[int] = None
    """Osoba z bazy Nexus bez kontraktu u tego klienta. Zapis linii dopina jej
    kontrakt w statusie ``draft``: dopiero on daje linii to, na czym stoi cała
    reszta modułu. ``draft`` — a nie ``active`` — bo aktywacja kontraktu ma
    własny, walidowany cykl życia (``contract_lifecycle.activate_contract``)
    i obsada zamówienia nie może go obchodzić bokiem."""

    rate_cost: MoneyPLN = Field(..., ge=0, max_digits=12, decimal_places=2)
    rate_revenue: MoneyPLN = Field(..., gt=0, max_digits=12, decimal_places=2)
    """Stawka przychodowa jest dzielnikiem (kwota→MD, przeliczenie przy
    zamianie kontraktora), więc zero jest odrzucane już na wejściu."""

    input_mode: Optional[str] = None
    input_value: Optional[MdValue] = Field(None, ge=0, max_digits=16, decimal_places=6)
    """Budżet MD linii. OPCJONALNY, bo linia na zamówieniu KOSZTOWYM go nie ma —
    tam pula jest wspólna i mieszka na zamówieniu, a nie przy osobie. Handler
    wymaga kompletu przy zamówieniu MD i odrzuca go przy kosztowym; walidacja
    nie może stać tutaj, bo schemat nie wie, do jakiego zamówienia trafia."""

    start_date: date
    end_date: Optional[date] = None
    job_id: Optional[int] = None

    @field_validator("input_mode")
    @classmethod
    def _mode(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in INPUT_MODES:
            raise ValueError("Tryb budżetu musi być 'md' albo 'amount'")
        return v

    @model_validator(mode="after")
    def _budget_is_all_or_nothing(self) -> "OrderLineCreate":
        """Tryb i wartość budżetu przychodzą razem albo wcale.

        Sam tryb bez wartości (albo odwrotnie) nie pozwala policzyć MD, a
        przepuszczenie tego dalej kończy się `md_total = None` przy
        `md_input_mode` ustawionym — czyli naruszeniem CHECK-a spójności
        w bazie, już w środku transakcji."""
        if (self.input_mode is None) != (self.input_value is None):
            raise ValueError("Budżet MD wymaga obu pól naraz: input_mode i input_value")
        return self

    @model_validator(mode="after")
    def _exactly_one_person_reference(self) -> "OrderLineCreate":
        """Ani zero, ani dwa wskazania osoby.

        Zero — nie wiadomo, kogo dodać. Dwa — trzeba by rozstrzygać, które
        wygrywa, a każde rozstrzygnięcie po cichu zignoruje jedno z pól i wpisze
        na zamówienie kogoś innego, niż widział operator.
        """
        if (self.contract_id is None) == (self.candidate_id is None):
            raise ValueError(
                "Wskaż osobę dokładnie jednym polem: contract_id albo candidate_id"
            )
        return self


class OrderGroupCreate(BaseModel):
    order_number: str = Field(..., min_length=1, max_length=64)
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None
    order_type: Optional[OrderType] = None
    """Jawny typ nowej grupy. ``None`` jest zgodnością ze starymi klientami;
    nowy ogólny formularz zawsze wysyła ``cost`` albo ``md``."""
    is_cost_based: bool = False
    is_md_budget_based: bool = False
    budget_amount: Optional[MoneyPLN] = Field(
        None, gt=0, max_digits=16, decimal_places=2
    )
    """Kwota całego zamówienia. Wymagana przy ``is_cost_based``; zero i wartości
    ujemne odrzucone na wejściu, bo budżet, z którego nic nie da się zdjąć, nie
    jest budżetem — a pusta pula od razu oznaczyłaby zamówienie jako wyczerpane."""
    md_budget_total: Optional[MdValue] = Field(
        None, gt=0, max_digits=16, decimal_places=6
    )
    """Wspólna liczba MD całego zamówienia."""

    lines: list[OrderLineCreate] = Field(default_factory=list)

    @model_validator(mode="after")
    def _group_budget_coherence(self) -> "OrderGroupCreate":
        if self.order_type == OrderType.periodic:
            raise ValueError("Zamówienie okresowe utwórz w formularzu standardowym")
        if self.order_type is not None:
            expected_cost = self.order_type == OrderType.cost
            expected_md = self.order_type == OrderType.md
            if (
                "is_cost_based" in self.model_fields_set
                and self.is_cost_based != expected_cost
            ):
                raise ValueError("Typ zamówienia jest sprzeczny z flagą kosztową")
            if (
                "is_md_budget_based" in self.model_fields_set
                and self.is_md_budget_based != expected_md
            ):
                raise ValueError("Typ zamówienia jest sprzeczny z flagą MD")
            self.is_cost_based = expected_cost
            self.is_md_budget_based = expected_md
        if self.is_cost_based and self.is_md_budget_based:
            raise ValueError("Zamówienie nie może być jednocześnie kosztowe i na MD")
        if self.is_cost_based and self.budget_amount is None:
            raise ValueError("Zamówienie kosztowe wymaga kwoty zamówienia")
        if not self.is_cost_based and self.budget_amount is not None:
            raise ValueError(
                "Kwotę zamówienia można podać tylko dla zamówienia kosztowego"
            )
        if self.is_md_budget_based and self.md_budget_total is None:
            raise ValueError("Zamówienie na MD wymaga wspólnego budżetu w MD")
        if not self.is_md_budget_based and self.md_budget_total is not None:
            raise ValueError("Wspólny budżet MD można podać tylko dla zamówienia na MD")
        return self


class OrderGroupUpdate(BaseModel):
    order_number: Optional[str] = Field(None, min_length=1, max_length=64)
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None
    budget_amount: Optional[MoneyPLN] = Field(
        None, gt=0, max_digits=16, decimal_places=2
    )
    """Korekta kwoty zamówienia kosztowego. Zmiana PRZELICZA pozostałość od
    nowa i potrafi zdjąć status „Wyczerpane" — podniesienie kwoty musi odsłonić
    budżet, inaczej zamówienie zostaje w zakończonych z dodatnią resztą."""

    budget_manual_adjustment: Optional[MoneyPLN] = Field(
        None, max_digits=16, decimal_places=2
    )
    """Ręczna korekta puli, trzymana OSOBNO od kwoty — dokładnie tak jak
    ``md_manual_adjustment`` przy liniach MD."""

    md_budget_total: Optional[MdValue] = Field(
        None, gt=0, max_digits=16, decimal_places=6
    )
    md_budget_manual_adjustment: Optional[MdValue] = Field(
        None, max_digits=16, decimal_places=6
    )


class OrderGroupClose(BaseModel):
    """Zakończenie zamówienia — data jest jedyną rzeczą, o którą pytamy."""

    closure_date: date
    closure_reason: Optional[str] = None


class OrderGroupExtend(BaseModel):
    """Przedłużenie: NOWE zamówienie kontynuujące poprzednie.

    Nie jest edycją poprzedniego. Numer, okres i budżety są inne, a poprzednie
    zamówienie musi zostać w rejestrze takie, jakie było — to na jego podstawie
    rozliczono już wystawione faktury.
    """

    order_number: str = Field(..., min_length=1, max_length=64)
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None
    budget_amount: Optional[MoneyPLN] = Field(
        None, gt=0, max_digits=16, decimal_places=2
    )
    md_budget_total: Optional[MdValue] = Field(
        None, gt=0, max_digits=16, decimal_places=6
    )
    lines: list[OrderLineCreate] = Field(default_factory=list)


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


class OrderOffboardingResolutionRequest(BaseModel):
    """Delivery Lead decision for one pending MD offboarding case."""

    action: Literal["remove", "transfer"]
    target_order_id: Optional[int] = Field(None, gt=0)
    rate_basis: Optional[Literal["departing", "recipient"]] = None
    expected_version: int = Field(..., ge=1)

    @model_validator(mode="after")
    def _coherent_decision(self):
        if self.action == "transfer":
            if self.target_order_id is None:
                raise ValueError("Przeniesienie wymaga konsultanta docelowego")
            if self.rate_basis is None:
                raise ValueError("Przeniesienie wymaga wyboru stawki")
        elif self.target_order_id is not None or self.rate_basis is not None:
            raise ValueError(
                "Usunięcie puli nie przyjmuje konsultanta ani podstawy stawki"
            )
        return self


# ── Wyjście ─────────────────────────────────────────────────────────────────


class OrderOffboardingCaseRead(BaseModel):
    """Durable pending/resolved state rendered next to an MD order line."""

    model_config = {"from_attributes": True}

    id: int
    contract_id: int
    order_id: int
    order_group_id: Optional[int] = None
    client_id: int
    effective_date: date
    status: Literal["pending", "resolved"]
    version: int

    uses_shared_md_pool: bool
    remaining_md_snapshot: MdValue
    rate_cost_snapshot: Optional[MoneyPLN] = None
    rate_revenue_snapshot: Optional[MoneyPLN] = None
    currency_snapshot: Optional[str] = None
    order_number_snapshot: Optional[str] = None

    resolution: Optional[Literal["remove", "transfer"]] = None
    target_order_id: Optional[int] = None
    rate_basis: Optional[Literal["departing", "recipient"]] = None
    resolution_payload: Optional[dict[str, Any]] = None
    resolved_at: Optional[datetime] = None
    resolved_by_user_id: Optional[int] = None
    created_by_user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime


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

    # ── Zamówienie kosztowe ──
    invoiced_total: Optional[MoneyPLN] = None
    """„Zafakturowano" — suma PEŁNYCH kwot faktur tej osoby, także tych, które
    nie zmieściły się w budżecie. `None` = linia nie jest na zamówieniu
    kosztowym; `0` = jest, ale nic jeszcze nie zafakturowano."""

    unsettled_total: Optional[MoneyPLN] = None
    """Ile z faktur tej osoby nie zmieściło się w budżecie zamówienia."""

    missing_consumption_month: Optional[str] = None
    """Ostatni zaimportowany miesiąc, w którym ta linia NIE ma zejścia —
    źródło komunikatu „Brak zejścia za {miesiąc}”. `None` = jest zejście albo
    nie było jeszcze żadnego importu."""

    offboarding_case: Optional[OrderOffboardingCaseRead] = None
    """Nierozwiązana lub historyczna decyzja po zakończeniu współpracy."""


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

    related_group_id: Optional[int] = None
    related_order_number: Optional[str] = None
    """Druga strona przejęcia zużycia MD — zamówienie, do którego prowadzi
    odsyłacz we wpisie ``transfer_md``.

    Pola stoją OSOBNO, a nie w ``payload``, bo ``payload`` znika w całości
    rolom bez ``VIEW_FINANCE`` (niesie stawki). Odsyłacz zbudowany z payloadu
    przestałby więc działać dokładnie tym rolom, które tę zakładkę widzą, a
    stawek widzieć nie mają. Numer i identyfikator zamówienia nie są
    informacją finansową."""


class OrderGroupRead(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    client_id: int
    order_number: str
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None
    created_at: datetime

    status: str = "active"
    status_label: str = "Aktywne"
    closure_date: Optional[date] = None
    closure_reason: Optional[str] = None
    order_type: Optional[OrderType] = None

    is_cost_based: bool = False
    budget_amount: Optional[MoneyPLN] = None
    budget_used: Optional[MoneyPLN] = None
    budget_remaining: Optional[MoneyPLN] = None
    """Trzy liczby, nie jedna. Ticket nazywa „zużyciem" wartość, która MALEJE —
    czyli resztę. Jedno pole podpisane „zużycie", a pokazujące resztę, jest
    pomyłką dokładnie w rozmowie o pieniądzach, więc front dostaje komplet."""

    budget_manual_adjustment: Optional[MoneyPLN] = None
    is_md_budget_based: bool = False
    md_budget_total: Optional[MdValue] = None
    md_budget_used: Optional[MdValue] = None
    md_budget_remaining: Optional[MdValue] = None
    md_budget_manual_adjustment: Optional[MdValue] = None
    predecessor_group_id: Optional[int] = None
    filename: Optional[str] = None
    has_file: bool = False
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    file_uploaded_at: Optional[datetime] = None
    can_add_consultant: bool = True
    """Wyliczane przez serwer. Front nie zna reguły „wyczerpane blokuje
    dodawanie", a przycisk, który na zapisie kończy się 409, czyta się jak
    „zapis nie działa", nie jak „tak ma być"."""

    lines: list[OrderLineRead] = Field(default_factory=list)
    active_consultants: int = 0
    event_count: int = 0
    # Zaplanowane kontynuacje nie są równorzędnymi kartami głównej listy.
    # Każda zachowuje pełny kształt (linie, stawki, MD), żeby można ją było
    # edytować/usunąć jeszcze przed datą wejścia w życie.
    future_orders: list["OrderGroupRead"] = Field(default_factory=list)


class OrderDraftRead(BaseModel):
    """Samodzielny szkic zamówienia w zakładce „Draft (do uzupełnienia)”.

    Szkice z hooka zatrudnienia („Oznacz jako podpisane” / pipeline „hired”)
    nie mają jeszcze grupy — do materializacji dochodzi dopiero przy
    aktywacji. Kształt celowo węższy niż ``OrderLineRead``: wiersz służy
    wyłącznie uzupełnieniu czterech pól aktywacji plus opcjonalnej liczby MD.
    """

    id: int
    contract_id: int
    consultant_name: str = ""
    title: str
    order_type: Optional[OrderType] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

    # Finansowe — zerowane dla ról bez dostępu do stawek (jak w liniach).
    rate_cost: Optional[MoneyPLN] = None
    """Efektywna stawka kosztowa umowy (harmonogram jest prawdą)."""
    rate_revenue: Optional[MoneyPLN] = None
    """``rate_client`` szkicu — do materializacji stawek linii MD."""

    # Liczba MD jest operacyjna, nie finansowa (jak md_total w liniach).
    md_quantity: Optional[MdValue] = None

    created_at: Optional[datetime] = None


class OrderGroupListResponse(BaseModel):
    groups: list[OrderGroupRead] = Field(default_factory=list)
    total_groups: int = 0
    total_consultants: int = 0
    suggested_order_type: OrderType = OrderType.periodic
    # Legacy zakładka „Draft (do uzupełnienia)” — tylko klienci, dla których
    # historyczny rejestr grup ją obsługiwał, i tylko szkice od jego wdrożenia.
    draft_orders: list[OrderDraftRead] = Field(default_factory=list)
    total_draft_orders: int = 0


class OrderGroupExportRequest(BaseModel):
    """Ordered group IDs currently visible after filters/search/sorting."""

    group_ids: list[int] = Field(default_factory=list, max_length=5000)


class OrderGroupEventsResponse(BaseModel):
    events: list[OrderGroupEventRead] = Field(default_factory=list)


class ConsultantOptionRead(BaseModel):
    """Pozycja pickera „Konsultant" — jedna osoba, jedno źródło pochodzenia."""

    candidate_id: int
    contract_id: Optional[int] = None
    """`null` = osoba bez kontraktu u tego klienta (źródło „Baza Nexus").
    Zapis linii dopnie jej kontrakt; front odsyła wtedy `candidate_id`."""

    full_name: str
    first_name: str = ""
    last_name: str = ""
    source: str
    source_label: str
    """Etykieta gotowa do wyświetlenia. Trzymana po stronie serwera razem
    z wartością `source`, żeby nazwa źródła nie rozjechała się między listą
    a historią zamówienia, która zapisuje ten sam tekst do bazy."""

    job_title: Optional[str] = None
    suggested_rate_cost: Optional[MoneyPLN] = None
    """Kanoniczna podpowiedź PLN/MD dla kompatybilności starszego frontendu."""

    suggested_contract_rate_cost: Optional[ContractRateValue] = None
    """Surowa efektywna stawka z aktywnego/kończącego się kontraktu tej osoby
    u bieżącego klienta. Zachowuje 3 miejsca po przecinku."""

    suggested_rate_cost_unit: Optional[RateUnit] = None
    suggested_rate_cost_currency: Optional[str] = None
    suggested_rate_cost_rate_to_pln: Optional[FxRateValue] = None
    """Metadane surowej podpowiedzi potrzebne do zapisu w PLN/MD. Wszystkie
    pola są `null`, gdy nie ma żywego kontraktu/stawki albo brakuje kursu FX."""

    has_different_client_contract_rates: bool = False
    """Czy inne nieanulowane kontrakty tej osoby u bieżącego klienta mają
    inną stawkę. Pole nie ujawnia kwot historycznych — tylko każe operatorowi
    zweryfikować podpowiedź przed zapisem."""


class ConsultantOptionsResponse(BaseModel):
    options: list[ConsultantOptionRead] = Field(default_factory=list)
    total: int = 0
    """Liczba WSZYSTKICH pasujących osób, także tych poza `limit`. Bez niej
    przycięcie listy byłoby cichym obcięciem — a lista bez ostrzeżenia czyta
    się jako komplet."""


class SwapPreview(BaseModel):
    """Podgląd przeliczenia MD przy zamianie — liczony po stronie serwera."""

    md_remaining_old: MdValue
    remaining_value_pln: Optional[MoneyPLN] = None
    md_total_new: MdValue
