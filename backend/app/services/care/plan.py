"""Plan kontaktów z konsultantem — liczony od startu kontraktu.

Reguła (makieta „Opieka”, 16.10.2026): dzień 7, 30 i 90 od startu, potem co
kwartał (6, 9, 12… miesięcy od startu) oraz 30 dni przed końcem zamówienia
albo umowy. Punkty po końcu współpracy nie powstają.

Wiersze ``contract_care_plan_items`` powstają z wyprzedzeniem
(``LOOKAHEAD_DAYS``), więc opiekun widzi następny kontakt, zanim wypadnie.
Przy pierwszym włączeniu modułu dla starego kontraktu nie zakładamy zaległości
sprzed ``LOOKBACK_DAYS`` — to nie były kontakty, które ktoś przegapił
w NEXUSIE, tylko historia sprzed modułu.

Plan dopisuje dzienny przebieg (``reminders.run_once``) i zapis, który zmienia
opiekuna (``ensure_plans`` zbiorczo: jeden DELETE i wielowierszowy INSERT),
a nie listy opieki przy odczycie — „Ten tydzień” i „Wszystkie kontrakty”
niczego nie zapisują (audyt wydajności 17.10.2026). Wyjątek: zakładka
„Opieka” jednego kontraktu dopisuje jego plan (dwie instrukcje), żeby
świeży kontrakt nie czekał na nocny przebieg.

„Następny kontakt” (karta kontraktu, „Moi konsultanci”, dzwonek opiekuna)
liczy jedna funkcja ``next_contact``: najwcześniejszy otwarty punkt planu
albo umówiony kontakt z ostatniej rozmowy, nie starszy niż ``LOOKBACK_DAYS``
(``live_follow_up`` — tej samej reguły używa „Ten tydzień”).
"""

from __future__ import annotations

import calendar
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional, Protocol

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract_care import CareConversation, CarePlanItem

FIXED_DAYS: tuple[tuple[str, int], ...] = (("day_7", 7), ("day_30", 30), ("day_90", 90))
QUARTER_MONTHS = 3
PRE_END_DAYS = 30
LOOKAHEAD_DAYS = 120
LOOKBACK_DAYS = 30
#: Rozmowa bez zaległości zamyka najbliższy punkt planu, którego termin wypada
#: najpóźniej tyle dni po niej.
CONVERSATION_COVERS_DAYS = 14

KIND_LABELS: dict[str, str] = {
    "day_7": "Dzień 7",
    "day_30": "Dzień 30",
    "day_90": "Dzień 90",
    "quarterly": "Kontakt kwartalny",
    "pre_end": "Przed końcem zamówienia",
}
#: Rodzaj i etykieta umówionego kontaktu (follow-up z ostatniej rozmowy).
FOLLOW_UP = "follow_up"
FOLLOW_UP_LABEL = "Umówiony kontakt"


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


class PlanContract(Protocol):
    """Kontrakt dla planu: id, start i najbliższy koniec współpracy."""

    @property
    def id(self) -> int: ...

    @property
    def start_date(self) -> Optional[date]: ...

    @property
    def end_date(self) -> Optional[date]: ...


@dataclass(frozen=True)
class _Target:
    id: int
    start_date: Optional[date]
    end_date: Optional[date]


#: Wiersze jednego INSERT-a (5 parametrów na wiersz, limit asyncpg 32 767).
_INSERT_CHUNK = 2000

_DELETE_STALE_PRE_END = text(
    "DELETE FROM contract_care_plan_items p "
    "WHERE p.contract_id = ANY(CAST(:ids AS integer[])) "
    "AND p.kind = 'pre_end' AND p.status = 'open' "
    "AND NOT EXISTS ("
    "SELECT 1 FROM unnest(CAST(:keep_ids AS integer[]), CAST(:keep_seqs AS integer[])) "
    "AS k(contract_id, seq) WHERE k.contract_id = p.contract_id AND k.seq = p.seq)"
)


def _current_pre_end(start: Optional[date], end: Optional[date]) -> Optional[int]:
    if end is None or start is None or end - timedelta(days=PRE_END_DAYS) < start:
        return None
    return end.toordinal()


async def ensure_plans(
    db: AsyncSession, contracts: Iterable[PlanContract], *, today: date
) -> int:
    """Dopisuje brakujące punkty planu wielu kontraktów naraz. Zwraca liczbę nowych.

    Jeden DELETE i wielowierszowy INSERT (w paczkach) zamiast dwóch instrukcji
    na kontrakt. Otwarty punkt „przed końcem” dla innej daty końca znika —
    koniec się przesunął albo umowa stała się bezterminowa.
    """

    items = list(contracts)
    if not items:
        return 0
    keep = [
        (contract.id, seq)
        for contract in items
        if (seq := _current_pre_end(contract.start_date, contract.end_date)) is not None
    ]
    await db.execute(
        _DELETE_STALE_PRE_END,
        {
            "ids": [contract.id for contract in items],
            "keep_ids": [contract_id for contract_id, _ in keep],
            "keep_seqs": [seq for _, seq in keep],
        },
    )
    rows = [
        {
            "contract_id": contract.id,
            "kind": slot.kind,
            "seq": slot.seq,
            "due_on": slot.due_on,
            "status": "open",
        }
        for contract in items
        if contract.start_date is not None
        for slot in planned_slots(contract.start_date, contract.end_date, today)
    ]
    created = 0
    for offset in range(0, len(rows), _INSERT_CHUNK):
        statement = (
            insert(CarePlanItem)
            .values(rows[offset : offset + _INSERT_CHUNK])
            .on_conflict_do_nothing(index_elements=["contract_id", "kind", "seq"])
            .returning(CarePlanItem.id)
        )
        created += len((await db.execute(statement)).scalars().all())
    return created


async def ensure_plan(
    db: AsyncSession,
    contract_id: int,
    *,
    start: Optional[date],
    end: Optional[date],
    today: date,
) -> int:
    """Plan jednego kontraktu (zakładka „Opieka” kontraktu, testy)."""

    return await ensure_plans(db, [_Target(contract_id, start, end)], today=today)


async def close_with_conversation(
    db: AsyncSession,
    conversation: CareConversation,
    *,
    actor_id: Optional[int],
    now: datetime,
    plan_item_id: Optional[int] = None,
) -> Optional[CarePlanItem]:
    """Rozmowa zamyka punkty planu i zwraca pierwszy z nich (do śladu).

    Zamyka WSZYSTKIE otwarte punkty z terminem w dniu rozmowy lub wcześniej
    (zaległe dzwoniłyby dalej mimo rozmowy) oraz punkt wskazany. Bez
    wskazania i bez zaległości — najbliższy punkt z terminem najpóźniej
    ``CONVERSATION_COVERS_DAYS`` po rozmowie, ale nie „przed końcem”: ten
    zostaje, dopóki jego termin jest w przyszłości. Wskazany punkt, którego
    nie ma albo jest zamknięty → ``None`` i nic się nie zmienia.
    """

    open_items = select(CarePlanItem).where(
        CarePlanItem.contract_id == conversation.contract_id,
        CarePlanItem.status == "open",
    )
    chosen: Optional[CarePlanItem] = None
    if plan_item_id is not None:
        chosen = (
            await db.execute(
                open_items.where(CarePlanItem.id == plan_item_id).with_for_update()
            )
        ).scalar_one_or_none()
        if chosen is None:
            return None
    items = list(
        (
            await db.scalars(
                open_items.where(CarePlanItem.due_on <= conversation.occurred_on)
                .order_by(CarePlanItem.due_on, CarePlanItem.id)
                .with_for_update()
            )
        ).all()
    )
    if chosen is None and not items:
        chosen = (
            await db.execute(
                open_items.where(
                    CarePlanItem.kind != "pre_end",
                    CarePlanItem.due_on
                    <= conversation.occurred_on
                    + timedelta(days=CONVERSATION_COVERS_DAYS),
                )
                .order_by(CarePlanItem.due_on, CarePlanItem.id)
                .limit(1)
                .with_for_update()
            )
        ).scalar_one_or_none()
    if chosen is not None and all(item.id != chosen.id for item in items):
        items.append(chosen)
    for item in items:
        item.status = "done"
        item.done_conversation_id = conversation.id
        item.resolved_by = actor_id
        item.resolved_at = now
    if chosen is not None:
        return chosen
    return items[0] if items else None


# ── Następny kontakt ────────────────────────────────────────────────────────


def contact_label(kind: str) -> str:
    """Etykieta punktu planu albo umówionego kontaktu (``FOLLOW_UP``)."""

    return FOLLOW_UP_LABEL if kind == FOLLOW_UP else KIND_LABELS.get(kind, kind)


@dataclass(frozen=True)
class NextContact:
    kind: str  # rodzaj punktu planu albo ``FOLLOW_UP``
    due_on: date
    plan_item_id: Optional[int] = None

    @property
    def label(self) -> str:
        return contact_label(self.kind)

    def payload(self, today: date) -> dict[str, Any]:
        return {
            "due_on": self.due_on,
            "label": self.label,
            "plan_item_id": self.plan_item_id,
            "overdue": self.due_on < today,
        }


def live_follow_up(latest: Optional[CareConversation], today: date) -> Optional[date]:
    """Umówiony kontakt z OSTATNIEJ rozmowy, nie starszy niż ``LOOKBACK_DAYS``.

    Nowsza rozmowa zamyka wcześniejszy follow-up. Rozmowy z importu niosą
    terminy sprzed lat — bez tej granicy każda byłaby wiecznie zaległa.
    """

    if latest is None or latest.follow_up_on is None:
        return None
    if latest.follow_up_on < today - timedelta(days=LOOKBACK_DAYS):
        return None
    return latest.follow_up_on


def next_contact(
    items: Iterable[CarePlanItem],
    latest: Optional[CareConversation],
    today: date,
) -> Optional[NextContact]:
    """Najbliższy kontakt: najwcześniejszy otwarty punkt planu albo follow-up.

    Remis wygrywa punkt planu (rozmowa go zamknie). ``items`` mogą zawierać
    zamknięte punkty — liczą się tylko otwarte.
    """

    item = min(
        (item for item in items if item.status == "open"),
        key=lambda item: (item.due_on, item.id),
        default=None,
    )
    follow_up = live_follow_up(latest, today)
    if follow_up is not None and (item is None or follow_up < item.due_on):
        return NextContact(FOLLOW_UP, follow_up)
    if item is None:
        return None
    return NextContact(item.kind, item.due_on, plan_item_id=item.id)


async def latest_conversations(
    db: AsyncSession, contract_ids: Sequence[int]
) -> dict[int, CareConversation]:
    """Ostatnia rozmowa każdego kontraktu (data, potem id)."""

    if not contract_ids:
        return {}
    rows = (
        await db.scalars(
            select(CareConversation)
            .where(CareConversation.contract_id.in_(list(contract_ids)))
            .order_by(
                CareConversation.contract_id,
                CareConversation.occurred_on.desc(),
                CareConversation.id.desc(),
            )
            .distinct(CareConversation.contract_id)
        )
    ).all()
    return {conversation.contract_id: conversation for conversation in rows}
