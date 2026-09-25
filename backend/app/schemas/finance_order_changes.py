"""Schematy Finanse → Zmiany w zamówieniach.

Pięć podzakładek: Zmiany · Wejścia · Zejścia · Kończące się zamówienia · Braki.

Kwoty idą jako liczby JSON (``MoneyPLN`` z ``schemas.finance``) — goły
``Decimal`` Pydantic serializuje jako string, a front sklejałby go zamiast
dodawać. Jednostka stawki jest zawsze obok kwoty: ``152`` bez jednostki nie
odróżnia stawki godzinowej od dziennej.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.finance import MoneyPLN

OrderTypeCode = Literal["periodic", "cost", "md"]


class OrderChangesPeriod(BaseModel):
    year: int
    month: int
    label: str


class OrderChangesCounts(BaseModel):
    changes: int
    entries: int
    exits: int
    ending: int
    gaps: int


class OrderItemCheck(BaseModel):
    """Kto i kiedy odhaczył pozycję jako „Zrobione"."""

    by_name: str
    at: datetime


class OrderPdfRef(BaseModel):
    """PDF zamówienia, do którego należy pozycja — ten sam plik, który widać
    w „Zamówieniach PDF" (miesiąc i klient prowadzą tam jednym kliknięciem)."""

    kind: Literal["order", "group", "amendment"]
    id: int
    month: str  # RRRR-MM — miesiąc startu, jak w „Zamówieniach PDF"
    client_id: int
    download_name: str


class OrderRef(BaseModel):
    order_id: Optional[int] = None
    order_group_id: Optional[int] = None
    contract_id: Optional[int] = None
    client_id: Optional[int] = None
    client_name: str
    consultant_name: str
    order_number: str
    # Pola karty zamówienia (0354). Klucz pozycji liczy serwer — ten sam
    # w odczycie, w odhaczeniu i w historii.
    item_key: str = ""
    order_start: Optional[date] = None
    order_end: Optional[date] = None
    pdf: Optional[OrderPdfRef] = None
    done: Optional[OrderItemCheck] = None
    # Kiedy i przez kogo pozycja weszła do systemu: wpis dziennika zmian albo
    # założenie zamówienia. Pozycje liczone z dat (zejście, brak) go nie mają.
    entered_at: Optional[datetime] = None
    entered_by: Optional[str] = None
    entered_automatically: bool = False
    from_order_mail: bool = False


class InvoiceLine(BaseModel):
    """Pozycja faktury cyklicznej Nordei zapisana przy zamówieniu (ticket 8).

    ``index`` to pozycja linii w zapisie zamówienia — pod nim idzie ręczna
    poprawka. ``[brak]`` w ``text`` = pole nieodczytane z PDF-a.
    """

    index: int
    consultant: Optional[str] = None
    text: str
    edited_by_name: Optional[str] = None
    edited_at: Optional[datetime] = None


class InvoiceLineUpdate(BaseModel):
    index: int = Field(ge=0)
    text: str = Field(min_length=1, max_length=500)


class InvoiceLinesResponse(BaseModel):
    order_id: int
    lines: list[InvoiceLine]


class OrderEntryItem(OrderRef):
    """Wejście = osoba, która zaczyna z nami współpracę po raz pierwszy.

    Kontynuacja u tego samego klienta, przejście do innego klienta i dodatkowy
    projekt NIE są wejściami — idą do Zmian (``OrderChangeItem``). Dlatego nie
    ma tu już pól ``is_continuation`` / ``additional_project``: po korekcie
    kwalifikacji byłyby zawsze fałszywe, a pole, które zawsze kłamie w jedną
    stronę, zaprasza do budowania na nim.

    Pierwsza współpraca wynika z UMOWY, nie tylko z wiersza zamówienia —
    rejestr zamówień bywa młodszy niż współpraca, którą opisuje.
    """

    start_date: Optional[date] = None
    end_date: Optional[date] = None
    rate_cost: Optional[MoneyPLN] = None
    rate_revenue: Optional[MoneyPLN] = None
    rate_unit: Optional[str] = None
    currency: Optional[str] = None
    order_type: OrderTypeCode
    status: str
    # Tylko Nordea: gotowa pozycja faktury (``None`` = inny klient).
    invoice_lines: Optional[list[InvoiceLine]] = None


# Bez „continuation": osoba, która pracuje dalej (następca albo linia MD
# z budżetem), nie jest zejściem i nie trafia na tę listę — stąd też brak pól
# o następcy.
#
# Werdykt rozdziela dwie podzakładki, które dzielą ten sam kształt wiersza:
# ``ended_intent`` (człowiek zapisał koniec współpracy) idzie do Zejść,
# a ``ending_pending`` / ``no_successor`` (kończy się samo ZAMÓWIENIE, przy
# żywej współpracy) — do „Kończących się zamówień". Bliźniaczy typ różniący
# się wyłącznie nazwą byłby drugim miejscem do rozjechania.
ExitVerdict = Literal["ended_intent", "no_successor", "ending_pending"]


class OrderExitItem(OrderRef):
    end_date: date
    start_date: Optional[date] = None
    rate_cost: Optional[MoneyPLN] = None
    rate_revenue: Optional[MoneyPLN] = None
    rate_unit: Optional[str] = None
    currency: Optional[str] = None
    order_type: OrderTypeCode
    verdict: ExitVerdict
    verdict_label: str
    intent: Optional[str] = None


# ``order_continuation`` / ``client_change`` / ``additional_project`` liczone są
# przy odczycie z zamówień startujących w miesiącu — nie ma ich w dzienniku
# ``order_change_events`` (i dobrze: CHECK na ``field`` zostaje nietknięty).
ChangeKind = Literal[
    "rate_cost",
    "rate_revenue",
    "end_date",
    "additional_project",
    "order_continuation",
    "client_change",
]


class OrderChangeItem(OrderRef):
    kind: ChangeKind
    # Wpis w ``order_change_events`` — pozycje liczone z zamówień go nie mają.
    event_id: Optional[int] = None
    occurred_at: Optional[datetime] = None
    effective_date: Optional[date] = None
    old_amount: Optional[MoneyPLN] = None
    new_amount: Optional[MoneyPLN] = None
    old_unit: Optional[str] = None
    new_unit: Optional[str] = None
    currency: Optional[str] = None
    # Waluta STAREJ strony zmiany stawki (``order_change_events.old_currency``).
    # Zmiana waluty bez zmiany kwoty jest zmianą — bez tego pola obie strony
    # renderowały się w nowej walucie („100 EUR → 100 EUR”). ``None`` = ta
    # sama co ``currency`` (wpisy sprzed zapisu waluty starej strony).
    old_currency: Optional[str] = None
    old_date: Optional[date] = None
    new_date: Optional[date] = None
    is_whole_order: bool = False
    source: Optional[Literal["user", "system"]] = None
    author_name: Optional[str] = None
    # Nowe zamówienie w trwającej współpracy (dodatkowy projekt, kontynuacja,
    # zmiana klienta): stawki nowego zamówienia, dane poprzedniego zamówienia
    # i klienci, u których osoba równolegle pracuje.
    rate_cost: Optional[MoneyPLN] = None
    rate_revenue: Optional[MoneyPLN] = None
    rate_unit: Optional[str] = None
    other_client_names: list[str] = []
    previous_order_number: Optional[str] = None
    previous_end_date: Optional[date] = None
    previous_client_name: Optional[str] = None
    start_date: Optional[date] = None
    # Początek współpracy odczytany z UMOWY, gdy poprzedniego zamówienia nie ma
    # w NEXUSIE. Bez tego kontynuacja renderuje się jako „—", czyli dokładnie
    # tak, jak utrata danych.
    engagement_since: Optional[date] = None
    # Status zamówienia dla pozycji liczonych z zamówień (nowe zamówienie w
    # trwającej współpracy) — szkic i zamówienie żywe to dla rozliczeń dwie
    # różne rzeczy, więc wchodzi do klucza odhaczenia.
    order_status: Optional[str] = None


class OrderGapItem(OrderRef):
    gap_id: int
    ended_on: date
    detected_on: date
    status: Literal["open", "filled_late"]
    resolved_order_number: Optional[str] = None
    resolved_at: Optional[datetime] = None
    delay_days: Optional[int] = None


OrderChangesTabCode = Literal["changes", "entries", "exits", "ending", "gaps"]


class SupersededCheck(BaseModel):
    """Odhaczona pozycja, której już nie ma w bieżącym widoku miesiąca.

    Pozycja liczona z bieżącego stanu (np. zejście z datą końca) znika po
    ponownej zmianie zamówienia — jej odhaczenie zostaje w historii karty
    („Zmieniono ponownie")."""

    item_key: str
    tab: OrderChangesTabCode
    order_id: Optional[int] = None
    order_group_id: Optional[int] = None
    summary: str
    done: OrderItemCheck


class OrderChangesResponse(BaseModel):
    period: OrderChangesPeriod
    counts: OrderChangesCounts
    changes: list[OrderChangeItem]
    entries: list[OrderEntryItem]
    exits: list[OrderExitItem]
    # Zamówienia kończące się bez kolejnego przy ŻYWEJ współpracy — ten sam
    # kształt wiersza co Zejścia, inne pytanie.
    ending_orders: list[OrderExitItem]
    gaps: list[OrderGapItem]
    # Pierwszy zapis w dzienniku zmian — miesiące sprzed tej daty nie mają
    # historii zmian stawek i dat (dziennik nie działał wstecz).
    changes_tracked_since: Optional[datetime] = None
    gaps_tracked_since: date
    open_gaps_total: int
    # Odhaczać mogą wyłącznie role Admin i Finanse (poza podglądem jako).
    can_check: bool = False
    superseded: list[SupersededCheck] = []


class OrderCheckRequest(BaseModel):
    year: int
    month: int
    item_key: str
    done: bool


class OrderCheckResponse(BaseModel):
    item_key: str
    done: Optional[OrderItemCheck] = None


class OrderChangesTabSummary(BaseModel):
    total: int
    todo: int


class OrderChangesSummaryResponse(BaseModel):
    """Liczniki „do zrobienia" bieżącego miesiąca — badge w menu Finansów."""

    period: OrderChangesPeriod
    tabs: dict[str, OrderChangesTabSummary]
    todo: int


class OrderHistoryEntry(BaseModel):
    at: datetime
    kind: Literal["change", "checked", "unchecked"]
    summary: str
    by_name: Optional[str] = None
    automatic: bool = False


class OrderHistoryResponse(BaseModel):
    items: list[OrderHistoryEntry]
