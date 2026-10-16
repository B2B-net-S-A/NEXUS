"""Plan kontaktów z konsultantem — liczony od startu kontraktu.

Reguła (makieta „Opieka”, 16.10.2026): dzień 7, 30 i 90 od startu, potem co
kwartał (6, 9, 12… miesięcy od startu) oraz 30 dni przed końcem zamówienia
albo umowy. Punkty po końcu współpracy nie powstają.

Wiersze ``contract_care_plan_items`` powstają z wyprzedzeniem
(``LOOKAHEAD_DAYS``), więc opiekun widzi następny kontakt, zanim wypadnie.
Przy pierwszym włączeniu modułu dla starego kontraktu nie zakładamy zaległości
sprzed ``LOOKBACK_DAYS`` — to nie były kontakty, które ktoś przegapił
w NEXUSIE, tylko historia sprzed modułu.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract_care import CareConversation, CarePlanItem

FIXED_DAYS: tuple[tuple[str, int], ...] = (("day_7", 7), ("day_30", 30), ("day_90", 90))
QUARTER_MONTHS = 3
PRE_END_DAYS = 30
LOOKAHEAD_DAYS = 120
LOOKBACK_DAYS = 30
#: Rozmowa zamyka punkt planu, którego termin wypada najpóźniej tyle dni po niej.
CONVERSATION_COVERS_DAYS = 14

KIND_LABELS: dict[str, str] = {
    "day_7": "Dzień 7",
    "day_30": "Dzień 30",
    "day_90": "Dzień 90",
    "quarterly": "Kontakt kwartalny",
    "pre_end": "Przed końcem zamówienia",
}


@dataclass(frozen=True)
class PlannedSlot:
    kind: str
    seq: int
    due_on: date


def add_months(day: date, months: int) -> date:
    """Ten sam dzień miesiąca ``months`` później (31.01 + 1 = 28/29.02)."""

    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def end_of_cooperation(
    contract_end: Optional[date], order_end: Optional[date]
) -> Optional[date]:
    """Najbliższy znany koniec: umowy albo bieżącego zamówienia."""

    known = [value for value in (contract_end, order_end) if value is not None]
    return min(known) if known else None


def planned_slots(
    start: date,
    end: Optional[date],
    today: date,
    *,
    lookahead_days: int = LOOKAHEAD_DAYS,
    lookback_days: int = LOOKBACK_DAYS,
) -> list[PlannedSlot]:
    """Punkty planu, których termin wypada w oknie [dziś − wstecz, dziś + naprzód]."""

    window_start = today - timedelta(days=lookback_days)
    window_end = today + timedelta(days=lookahead_days)
    slots: list[PlannedSlot] = []

    def add(kind: str, seq: int, due_on: date) -> None:
        if kind != "pre_end" and end is not None and due_on > end:
            return
        if window_start <= due_on <= window_end:
            slots.append(PlannedSlot(kind, seq, due_on))

    for kind, days in FIXED_DAYS:
        add(kind, 0, start + timedelta(days=days))
    quarter = 1
    while True:
        due_on = add_months(start, QUARTER_MONTHS * (quarter + 1))
        if due_on > window_end or (end is not None and due_on > end):
            break
        add("quarterly", quarter, due_on)
        quarter += 1
    if end is not None:
        due_on = end - timedelta(days=PRE_END_DAYS)
        if due_on >= start:
            # ``seq`` = dzień końca: przedłużenie daje nowy punkt, stary znika.
            add("pre_end", end.toordinal(), due_on)
    return slots


async def ensure_plan(
    db: AsyncSession,
    contract_id: int,
    *,
    start: Optional[date],
    end: Optional[date],
    today: date,
) -> int:
    """Dopisuje brakujące punkty planu (idempotentnie). Zwraca liczbę nowych.

    Otwarty punkt „przed końcem” dla innej daty końca znika — koniec się
    przesunął albo umowa stała się bezterminowa.
    """

    current_pre_end = (
        end.toordinal()
        if end is not None
        and start is not None
        and end - timedelta(days=PRE_END_DAYS) >= start
        else None
    )
    stale = delete(CarePlanItem).where(
        CarePlanItem.contract_id == contract_id,
        CarePlanItem.kind == "pre_end",
        CarePlanItem.status == "open",
    )
    if current_pre_end is not None:
        stale = stale.where(CarePlanItem.seq != current_pre_end)
    await db.execute(stale)
    if start is None:
        return 0
    slots = planned_slots(start, end, today)
    if not slots:
        return 0
    statement = (
        insert(CarePlanItem)
        .values(
            [
                {
                    "contract_id": contract_id,
                    "kind": slot.kind,
                    "seq": slot.seq,
                    "due_on": slot.due_on,
                    "status": "open",
                }
                for slot in slots
            ]
        )
        .on_conflict_do_nothing(
            index_elements=["contract_id", "kind", "seq"],
        )
        .returning(CarePlanItem.id)
    )
    return len((await db.execute(statement)).scalars().all())


async def close_with_conversation(
    db: AsyncSession,
    conversation: CareConversation,
    *,
    actor_id: Optional[int],
    now: datetime,
    plan_item_id: Optional[int] = None,
) -> Optional[CarePlanItem]:
    """Rozmowa zamyka punkt planu: wskazany albo najwcześniejszy otwarty,
    którego termin wypada najpóźniej ``CONVERSATION_COVERS_DAYS`` po rozmowie."""

    query = select(CarePlanItem).where(
        CarePlanItem.contract_id == conversation.contract_id,
        CarePlanItem.status == "open",
    )
    if plan_item_id is not None:
        query = query.where(CarePlanItem.id == plan_item_id)
    else:
        query = query.where(
            CarePlanItem.due_on
            <= conversation.occurred_on + timedelta(days=CONVERSATION_COVERS_DAYS)
        ).order_by(CarePlanItem.due_on, CarePlanItem.id)
    item = (await db.execute(query.limit(1).with_for_update())).scalar_one_or_none()
    if item is None:
        return None
    item.status = "done"
    item.done_conversation_id = conversation.id
    item.resolved_by = actor_id
    item.resolved_at = now
    return item


def next_open(items: Iterable[CarePlanItem]) -> Optional[CarePlanItem]:
    open_items = [item for item in items if item.status == "open"]
    return min(open_items, key=lambda item: (item.due_on, item.id), default=None)
