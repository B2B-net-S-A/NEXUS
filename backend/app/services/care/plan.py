"""Plan kontaktów z konsultantem — liczony od startu kontraktu i rytmu.

Reguła (etap 3, O7, 17.10.2026): kamienie — dzień 7 od startu i 30 dni
przed końcem zamówienia albo umowy — zostają przy każdym rytmie, także przy
wstrzymaniu; między nimi rozmowy według rytmu konsultanta
(``cadence_rules``: domyślnie co 2 tygodnie przez pierwsze 90 dni, potem co
miesiąc). Punkty po końcu współpracy nie powstają. Do 17.10.2026 plan był
stały (dzień 7, 30, 90, potem co kwartał) — takie punkty w bazie zostają
jako historia, nowe powstają z rytmu.

Wiersze ``contract_care_plan_items`` powstają z wyprzedzeniem
(``LOOKAHEAD_DAYS``), więc opiekun widzi następny kontakt, zanim wypadnie.
Przy pierwszym włączeniu modułu dla starego kontraktu nie zakładamy zaległości
sprzed ``LOOKBACK_DAYS`` — to nie były kontakty, które ktoś przegapił
w NEXUSIE, tylko historia sprzed modułu. Zmiana rytmu zdejmuje otwarte
przyszłe rozmowy z rytmu, których nowy rytm już nie ma; zaległe i dzisiejsza
zostają (przegląd 17.10.2026).

Rozmowa pokrywa wcześniejsze punkty (przegląd 17.10.2026): punkt z terminem
nie późniejszym niż ostatnia rozmowa opiekuna z konsultantem
(``care_conversations.occurred_on``, także z importu Compassa) nie powstaje,
a już otwarty ``ensure_plans`` zamyka tą rozmową (``done_conversation_id`` =
pierwsza rozmowa w dniu terminu albo po nim, ślad ``care.plan_covered``) —
po włączeniu modułu kontrakt, z którym opiekun rozmawiał po terminie, nie
startuje z zaległością. Kontrakt bez żadnej rozmowy ma ją dalej.

Plan dopisuje dzienny przebieg (``reminders.run_once``), zmiana rytmu i zapis,
który zmienia opiekuna (``ensure_plans`` zbiorczo: jeden DELETE na rodzaj
i wielowierszowy INSERT), a nie listy opieki przy odczycie — „Ten tydzień”,
„Konsultanci” i „Przydział” niczego nie zapisują (audyt wydajności
17.10.2026). Wyjątek: zakładka „Opieka” jednego kontraktu dopisuje jego plan,
żeby świeży kontrakt nie czekał na nocny przebieg.

„Następny kontakt” (karta kontraktu, „Konsultanci”, dzwonek opiekuna)
liczy jedna funkcja ``next_contact``: najwcześniejszy otwarty punkt planu
albo umówiony kontakt z ostatniej rozmowy, nie starszy niż ``LOOKBACK_DAYS``
(``live_follow_up`` — tej samej reguły używa „Ten tydzień”).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Optional, Protocol

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract_care import CareCadencePeriod, CareConversation, CarePlanItem
from app.services.care.cadence_rules import PeriodLike, regular_dates
from app.services.care.cadence_rules import add_months as add_months
from app.services.hr import audit

#: Kamień po starcie i przed końcem zamówienia albo umowy.
FIRST_WEEK_DAYS = 7
PRE_END_DAYS = 30
#: Rozmowa z rytmu najwyżej tyle dni od kamienia to ta sama rozmowa.
MILESTONE_MERGE_DAYS = 6
LOOKAHEAD_DAYS = 120
LOOKBACK_DAYS = 30
#: Rozmowa bez zaległości zamyka najbliższy punkt planu, którego termin wypada
#: najpóźniej tyle dni po niej.
CONVERSATION_COVERS_DAYS = 14

KIND_LABELS: dict[str, str] = {
    "day_7": "Dzień 7",
    "cadence": "Rozmowa według rytmu",
    "pre_end": "Przed końcem zamówienia",
    # Stały plan sprzed 17.10.2026 — punkty zostają w historii.
    "day_30": "Dzień 30",
    "day_90": "Dzień 90",
    "quarterly": "Kontakt kwartalny",
}
#: Rodzaj i etykieta umówionego kontaktu (follow-up z ostatniej rozmowy).
FOLLOW_UP = "follow_up"
FOLLOW_UP_LABEL = "Umówiony kontakt"


@dataclass(frozen=True)
class PlannedSlot:
    kind: str
    seq: int
    due_on: date


def end_of_cooperation(
    contract_end: Optional[date], order_end: Optional[date]
) -> Optional[date]:
    """Najbliższy znany koniec: umowy albo bieżącego zamówienia."""

    known = [value for value in (contract_end, order_end) if value is not None]
    return min(known) if known else None


def slots_between(
    start: date,
    end: Optional[date],
    periods: Sequence[PeriodLike],
    first: date,
    last: date,
) -> list[PlannedSlot]:
    """Punkty planu z terminem w [``first``, ``last``]: kamienie i rytm."""

    milestones: list[PlannedSlot] = []
    week = start + timedelta(days=FIRST_WEEK_DAYS)
    if end is None or week <= end:
        milestones.append(PlannedSlot("day_7", 0, week))
    if end is not None and end - timedelta(days=PRE_END_DAYS) >= start:
        # ``seq`` = dzień końca: przedłużenie daje nowy punkt, stary znika.
        milestones.append(
            PlannedSlot("pre_end", end.toordinal(), end - timedelta(days=PRE_END_DAYS))
        )
    horizon = last if end is None else min(last, end)
    regular = [
        PlannedSlot("cadence", due.toordinal(), due)
        for due in regular_dates(start, periods, horizon)
        if all(
            abs((due - stone.due_on).days) > MILESTONE_MERGE_DAYS
            for stone in milestones
        )
    ]
    return sorted(
        (slot for slot in (*milestones, *regular) if first <= slot.due_on <= last),
        key=lambda slot: (slot.due_on, slot.kind),
    )


def planned_slots(
    start: date,
    end: Optional[date],
    today: date,
    *,
    periods: Sequence[PeriodLike] = (),
    lookahead_days: int = LOOKAHEAD_DAYS,
    lookback_days: int = LOOKBACK_DAYS,
) -> list[PlannedSlot]:
    """Punkty planu, których termin wypada w oknie [dziś − wstecz, dziś + naprzód]."""

    return slots_between(
        start,
        end,
        periods,
        today - timedelta(days=lookback_days),
        today + timedelta(days=lookahead_days),
    )


def conversations_between(
    start: Optional[date],
    end: Optional[date],
    periods: Sequence[PeriodLike],
    first: date,
    last: date,
) -> int:
    """Ile rozmów (kamienie i rytm) wypada w [``first``, ``last``] — obciążenie."""

    if start is None:
        return 0
    return len(slots_between(start, end, periods, first, last))


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
#: Otwarte przyszłe rozmowy z rytmu, których obecny rytm już nie ma (zmiana
#: rytmu, krótszy koniec). Zaległe i dzisiejsza zostają — wypadły w dawnym
#: rytmie; zmiana w dniu rozmowy nie może jej zdjąć, bo rozmowa zapisana
#: potem bez wskazania punktu zamknęłaby pierwszą rozmowę nowego rytmu.
_DELETE_STALE_CADENCE = text(
    "DELETE FROM contract_care_plan_items p "
    "WHERE p.contract_id = ANY(CAST(:ids AS integer[])) "
    "AND p.kind = 'cadence' AND p.status = 'open' AND p.due_on > :today "
    "AND NOT EXISTS ("
    "SELECT 1 FROM unnest(CAST(:keep_ids AS integer[]), CAST(:keep_seqs AS integer[])) "
    "AS k(contract_id, seq) WHERE k.contract_id = p.contract_id AND k.seq = p.seq)"
)

#: Otwarte punkty z terminem nie późniejszym niż rozmowa z konsultantem —
#: zamyka je pierwsza rozmowa w dniu terminu albo po nim (rozmowy z importu
#: nie zamykały planu, a plan powstaje z ``LOOKBACK_DAYS`` wstecz).
_CLOSE_COVERED = text(
    "UPDATE contract_care_plan_items p SET status = 'done', "
    "done_conversation_id = ("
    "SELECT c.id FROM care_conversations c "
    "WHERE c.contract_id = p.contract_id AND c.occurred_on >= p.due_on "
    "ORDER BY c.occurred_on, c.id LIMIT 1), "
    "resolved_by = NULL, resolved_at = now() "
    "WHERE p.contract_id = ANY(CAST(:ids AS integer[])) AND p.status = 'open' "
    "AND EXISTS (SELECT 1 FROM care_conversations c "
    "WHERE c.contract_id = p.contract_id AND c.occurred_on >= p.due_on) "
    "RETURNING p.id, p.contract_id, p.done_conversation_id"
)


def _current_pre_end(start: Optional[date], end: Optional[date]) -> Optional[int]:
    if end is None or start is None or end - timedelta(days=PRE_END_DAYS) < start:
        return None
    return end.toordinal()


async def periods_by_contract(
    db: AsyncSession, contract_ids: Iterable[int]
) -> dict[int, list[CareCadencePeriod]]:
    """Okresy rytmu kontraktów (od najstarszego)."""

    ids = sorted(set(contract_ids))
    out: dict[int, list[CareCadencePeriod]] = defaultdict(list)
    if not ids:
        return out
    for period in (
        await db.scalars(
            select(CareCadencePeriod)
            .where(CareCadencePeriod.contract_id.in_(ids))
            .order_by(
                CareCadencePeriod.contract_id,
                CareCadencePeriod.starts_on,
                CareCadencePeriod.id,
            )
        )
    ).all():
        out[period.contract_id].append(period)
    return out


async def last_talk_days(
    db: AsyncSession, contract_ids: Sequence[int]
) -> dict[int, date]:
    """Dzień ostatniej rozmowy z konsultantem per kontrakt (także z importu)."""

    if not contract_ids:
        return {}
    rows = await db.execute(
        select(CareConversation.contract_id, func.max(CareConversation.occurred_on))
        .where(CareConversation.contract_id.in_(list(contract_ids)))
        .group_by(CareConversation.contract_id)
    )
    return {contract_id: day for contract_id, day in rows.all()}


async def close_covered(db: AsyncSession, contract_ids: Sequence[int]) -> int:
    """Zamyka otwarte punkty pokryte późniejszą rozmową; ślad per kontrakt."""

    if not contract_ids:
        return 0
    closed: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for item_id, contract_id, conversation_id in (
        await db.execute(_CLOSE_COVERED, {"ids": list(contract_ids)})
    ).all():
        closed[contract_id].append((item_id, conversation_id))
    for contract_id, rows in sorted(closed.items()):
        audit.record(
            db,
            actor_user_id=None,
            subject_user_id=None,
            entity_type="contract",
            entity_id=contract_id,
            action="care.plan_covered",
            details={
                "plan_item_ids": sorted(item_id for item_id, _ in rows),
                "conversation_ids": sorted({cid for _, cid in rows}),
            },
        )
    return sum(len(rows) for rows in closed.values())


async def ensure_plans(
    db: AsyncSession, contracts: Iterable[PlanContract], *, today: date
) -> int:
    """Dopisuje brakujące punkty planu wielu kontraktów naraz. Zwraca liczbę nowych.

    Jeden DELETE na rodzaj i wielowierszowy INSERT (w paczkach) zamiast
    instrukcji na kontrakt. Otwarty punkt „przed końcem” dla innej daty końca
    znika — koniec się przesunął albo umowa stała się bezterminowa — a otwarta
    przyszła rozmowa z rytmu, której obecny rytm nie ma, też. Punkty pokryte
    ostatnią rozmową nie powstają, a otwarte zamyka ``close_covered``.
    """

    items = list(contracts)
    if not items:
        return 0
    ids = [contract.id for contract in items]
    periods = await periods_by_contract(db, ids)
    talked = await last_talk_days(db, ids)
    planned = {
        contract.id: [
            slot
            for slot in planned_slots(
                contract.start_date,
                contract.end_date,
                today,
                periods=periods.get(contract.id, ()),
            )
            if contract.id not in talked or slot.due_on > talked[contract.id]
        ]
        for contract in items
        if contract.start_date is not None
    }
    keep = [
        (contract.id, seq)
        for contract in items
        if (seq := _current_pre_end(contract.start_date, contract.end_date)) is not None
    ]
    await db.execute(
        _DELETE_STALE_PRE_END,
        {
            "ids": ids,
            "keep_ids": [contract_id for contract_id, _ in keep],
            "keep_seqs": [seq for _, seq in keep],
        },
    )
    rhythm = [
        (contract_id, slot.seq)
        for contract_id, slots in planned.items()
        for slot in slots
        if slot.kind == "cadence"
    ]
    await db.execute(
        _DELETE_STALE_CADENCE,
        {
            "ids": ids,
            "today": today,
            "keep_ids": [contract_id for contract_id, _ in rhythm],
            "keep_seqs": [seq for _, seq in rhythm],
        },
    )
    rows = [
        {
            "contract_id": contract_id,
            "kind": slot.kind,
            "seq": slot.seq,
            "due_on": slot.due_on,
            "status": "open",
        }
        for contract_id, slots in planned.items()
        for slot in slots
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
    await close_covered(db, [cid for cid in ids if cid in talked])
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


async def open_items(
    db: AsyncSession, contract_ids: Sequence[int]
) -> dict[int, list[CarePlanItem]]:
    """Otwarte punkty planu kontraktów (od najbliższego terminu)."""

    out: dict[int, list[CarePlanItem]] = {cid: [] for cid in contract_ids}
    if not contract_ids:
        return out
    for item in (
        await db.scalars(
            select(CarePlanItem)
            .where(
                CarePlanItem.contract_id.in_(list(contract_ids)),
                CarePlanItem.status == "open",
            )
            .order_by(CarePlanItem.due_on, CarePlanItem.id)
        )
    ).all():
        out.setdefault(item.contract_id, []).append(item)
    return out


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
