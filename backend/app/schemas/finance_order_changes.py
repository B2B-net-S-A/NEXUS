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

from pydantic import BaseModel

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


class OrderRef(BaseModel):
    order_id: Optional[int] = None
    order_group_id: Optional[int] = None
    contract_id: Optional[int] = None
    client_id: Optional[int] = None
    client_name: str
    consultant_name: str
    order_number: str


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
    occurred_at: Optional[datetime] = None
    effective_date: Optional[date] = None
    old_amount: Optional[MoneyPLN] = None
    new_amount: Optional[MoneyPLN] = None
    old_unit: Optional[str] = None
    new_unit: Optional[str] = None
    currency: Optional[str] = None
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


class OrderGapItem(OrderRef):
    gap_id: int
    ended_on: date
    detected_on: date
    status: Literal["open", "filled_late"]
    resolved_order_number: Optional[str] = None
    resolved_at: Optional[datetime] = None
    delay_days: Optional[int] = None


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
