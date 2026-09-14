"""Schematy Finanse → Zmiany w zamówieniach (Zmiany · Wejścia · Zejścia · Braki).

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
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    rate_cost: Optional[MoneyPLN] = None
    rate_revenue: Optional[MoneyPLN] = None
    rate_unit: Optional[str] = None
    currency: Optional[str] = None
    order_type: OrderTypeCode
    status: str
    is_continuation: bool
    previous_order_number: Optional[str] = None
    previous_end_date: Optional[date] = None
    additional_project: bool = False


ExitVerdict = Literal["continuation", "ended_intent", "no_successor", "ending_pending"]


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
    successor_order_number: Optional[str] = None
    successor_start_date: Optional[date] = None
    intent: Optional[str] = None


ChangeKind = Literal["rate_cost", "rate_revenue", "end_date", "additional_project"]


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
    # Dodatkowy projekt: stawki nowego zamówienia i klienci, u których osoba
    # równolegle pracuje.
    rate_cost: Optional[MoneyPLN] = None
    rate_revenue: Optional[MoneyPLN] = None
    rate_unit: Optional[str] = None
    other_client_names: list[str] = []


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
    gaps: list[OrderGapItem]
    # Pierwszy zapis w dzienniku zmian — miesiące sprzed tej daty nie mają
    # historii zmian stawek i dat (dziennik nie działał wstecz).
    changes_tracked_since: Optional[datetime] = None
    gaps_tracked_since: date
    open_gaps_total: int
