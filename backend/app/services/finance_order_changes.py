"""Finanse → Zmiany w zamówieniach: odczyt pięciu podzakładek i eksport.

Wszystkie listy liczone są w jednym odczycie, żeby liczniki przy podzakładkach
zawsze zgadzały się z ich treścią.

* **Wejścia** — WYŁĄCZNIE osoby zaczynające z nami współpracę po raz pierwszy.
  Dowodem wcześniejszej współpracy jest zamówienie **albo UMOWA**: rejestr
  zamówień jest młodszy niż współpraca, którą opisuje, więc konsultant
  z umową od grudnia i pierwszym wierszem zamówienia z września wyglądał
  w Wejściach jak nowa osoba (zgłoszenie 09.2026).
* **Zejścia** — osoby z zapisanym końcem współpracy (``load_ending_intents``):
  wypowiedziana/zakończona umowa, zamiana kontraktora, decyzja DL po
  offboardingu MD, usunięcie z zamówienia, zostawienie jako historia.
  Wspólny mianownik: człowiek świadomie zapisał, że ta osoba schodzi.
* **Kończące się zamówienia** — zamówienie kończy się (albo skończyło) bez
  kolejnego, a współpraca TRWA. To nie jest zejście i do 09.2026 mieszało się
  z nimi w jednej zakładce: „Kończy się 30.09 — na razie brak kolejnego
  zamówienia" czytało się jak rozstanie z konsultantem, który pracuje dalej.
* **Zmiany** — wszystko, co dzieje się w TRWAJĄCEJ współpracy: dziennik
  ``order_change_events`` z datą WPROWADZENIA w miesiącu (decyzja Artura
  14.09) plus nowe zamówienia osób, które już z nami pracują — kontynuacja
  u tego samego klienta, zmiana klienta i dodatkowy projekt.
* **Braki** — ``order_gaps`` z dniem wykrycia w miesiącu, także uzupełnione
  z opóźnieniem (wpis historyczny). Kwalifikacja bez zmian.

Zakładka ma nazywać się tak, jak to, co w niej jest — obie korekty (09.2026)
wynikły z tej jednej zasady.

**Zmiany stawek nie mają progu** — do Zmian trafia KAŻDA różnica stawki
kosztowej i przychodowej. Filtruje je wyłącznie ``order_change_audit``
(pierwsze wpisanie stawki to nie zmiana, szkice i anulowane nie liczą się).

Filtry (szukaj / klient / zakres dat) liczy ``apply_filters`` na gotowych
listach — to jedno miejsce obsługuje i widok, i eksport, więc plik nie może
pokazać czego innego niż ekran.

Odczyt niczego nie zapisuje — braki wykrywa pętla ``order_gaps``, a zamyka
zapis zamówienia.
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Iterable, Literal, Optional, Sequence
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ, business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.contract import Contract, ContractStatus
from app.models.order_change_event import OrderChangeEvent
from app.models.order_gap import GAP_STATUS_FILLED_LATE, GAP_STATUS_OPEN, OrderGap
from app.models.user import User
from app.schemas.finance_order_changes import (
    OrderChangeItem,
    OrderChangesCounts,
    OrderChangesPeriod,
    OrderChangesResponse,
    OrderEntryItem,
    OrderExitItem,
    OrderGapItem,
)
from app.services.client_identity import client_display_name_expression
from app.services.order_excel_export import _safe_text
from app.services.order_facts import (
    INTENT_LABELS,
    OrderFact,
    effective_end_expr,
    effective_start_expr,
    load_ending_intents,
    load_facts,
    load_siblings,
    local_day_start,
    previous_of,
    siblings_of,
    successor_of,
)

MONTH_LABELS_PL = (
    "Styczeń",
    "Luty",
    "Marzec",
    "Kwiecień",
    "Maj",
    "Czerwiec",
    "Lipiec",
    "Sierpień",
    "Wrzesień",
    "Październik",
    "Listopad",
    "Grudzień",
)

ORDER_TYPE_LABELS = {"periodic": "B2B", "cost": "Kosztowe", "md": "MD"}
UNIT_LABELS = {"hourly": "h", "daily": "dzień", "monthly": "mc", "md": "MD"}


@dataclass(frozen=True)
class MonthWindow:
    year: int
    month: int
    first: date
    last: date

    @property
    def next_first(self) -> date:
        return date(self.year + (self.month // 12), self.month % 12 + 1, 1)

    @classmethod
    def of(cls, year: int, month: int) -> "MonthWindow":
        first = date(year, month, 1)
        following = date(year + (month // 12), month % 12 + 1, 1)
        return cls(
            year=year,
            month=month,
            first=first,
            last=date.fromordinal(following.toordinal() - 1),
        )


def period_label(year: int, month: int) -> str:
    return f"{MONTH_LABELS_PL[month - 1]} {year}"


def _fmt_date(value: Optional[date]) -> str:
    return value.strftime("%d.%m.%Y") if value else "—"


def _ref(fact: OrderFact) -> dict:
    return {
        "order_id": fact.order_id,
        "order_group_id": fact.order_group_id,
        "contract_id": fact.contract_id,
        "client_id": fact.client_id,
        "client_name": fact.client_name,
        "consultant_name": fact.consultant_name,
        "order_number": fact.number,
    }


def _sort_key(item) -> tuple:
    return (item.consultant_name.lower(), item.client_name.lower(), item.order_number)


# ── Wejścia ──────────────────────────────────────────────────────────────────

EntryKind = Literal["new", "additional_project", "order_continuation", "client_change"]


@dataclass(frozen=True)
class EntryClass:
    """Czym jest zamówienie startujące w miesiącu dla OSOBY, nie dla klienta.

    Pola poza ``kind`` są PREZENTACYJNE, nie surowymi ``OrderFact``ami: dowód
    wcześniejszej współpracy bywa umową, a nie zamówieniem, i wtedy nie ma
    czego włożyć w ``OrderFact``. ``previous`` zostaje wyłącznie dla numeru
    i daty końca poprzedniego ZAMÓWIENIA.
    """

    kind: EntryKind
    previous: Optional[OrderFact] = None
    running_client_names: tuple[str, ...] = ()
    previous_client_name: Optional[str] = None
    engagement_since: Optional[date] = None


@dataclass(frozen=True)
class Engagement:
    """Współpraca odczytana z UMOWY — dowód pracy sprzed pierwszego zamówienia."""

    client_id: Optional[int]
    client_name: str
    start: date
    end: Optional[date]
    closed: bool

    def runs_on(self, day: date) -> bool:
        if self.end is not None:
            return self.end >= day
        # Umowa bezterminowa trwa, chyba że ktoś ją zamknął bez daty końca.
        return not self.closed


async def _prior_engagements(
    db: AsyncSession, people: set[int], window: MonthWindow
) -> dict[int, list[Engagement]]:
    """Umowy osób z Wejść, które zaczęły się PRZED tym miesiącem.

    Próg to pierwszy dzień miesiąca, nie dzień startu zamówienia — i to jest
    decyzja, nie skrót. Osobie faktycznie nowej zakłada się umowę razem
    z pierwszym zamówieniem, często z datą o kilka dni wcześniejszą (umowa
    01.09, zamówienie 15.09); próg „ściśle przed startem zamówienia" zdjąłby
    z Wejść także takie osoby i zakładka zrobiłaby się pusta. Próg miesięczny
    czyta się dokładnie tak, jak brzmi obietnica zakładki: PIERWSZA współpraca
    w tym miesiącu.

    ``draft`` i ``void`` nie liczą się — lustro reguły, która w tym samym
    klasyfikatorze wyklucza szkice zamówień: szkic to plan, nie praca,
    a ``void`` to unieważnienie.
    """

    if not people:
        return {}
    rows = (
        await db.execute(
            select(
                Contract.candidate_id,
                Contract.client_id,
                client_display_name_expression().label("client_name"),
                Contract.start_date,
                Contract.end_date,
                Contract.status,
            )
            .outerjoin(Client, Client.id == Contract.client_id)
            .where(
                Contract.candidate_id.in_(sorted(people)),
                Contract.status.notin_((ContractStatus.draft, ContractStatus.void)),
                Contract.start_date.is_not(None),
                Contract.start_date < window.first,
            )
        )
    ).all()
    result: dict[int, list[Engagement]] = {}
    for row in rows:
        result.setdefault(row.candidate_id, []).append(
            Engagement(
                client_id=row.client_id,
                client_name=row.client_name or "—",
                start=row.start_date,
                end=row.end_date,
                closed=row.status
                in (ContractStatus.ended.value, ContractStatus.void.value),
            )
        )
    return result


def _precedes(other: OrderFact, fact: OrderFact) -> bool:
    """Czy ``other`` istniało już, gdy zaczynało się ``fact``.

    Zamówienie osoby zaczynające się PÓŹNIEJ nie czyni z niej „już
    współpracującej" — pokaże się we własnym miesiącu i wtedy zostanie
    sklasyfikowane. Dwa zamówienia tej samej osoby startujące TEGO SAMEGO DNIA
    u dwóch klientów: pierwszeństwo ma niższe id, żeby osoba naprawdę nowa
    pokazała się w Wejściach raz, a nie zniknęła z nich całkiem.
    """

    if other.start is None:
        return True
    if fact.start is None:
        return False
    if other.start < fact.start:
        return True
    return other.start == fact.start and other.order_id < fact.order_id


def _runs_on(other: OrderFact, day: date) -> bool:
    if other.end is None:
        return other.status != ClientOrderStatus.completed.value
    return other.end >= day


async def _classify_entries(
    db: AsyncSession,
    entry_facts: list[OrderFact],
    siblings: dict,
    window: MonthWindow,
) -> dict[int, EntryClass]:
    """Wejście czy zmiana w trwającej współpracy — jedna reguła, pierwsze trafienie.

    Dowodem wcześniejszej współpracy jest ZAMÓWIENIE albo UMOWA. Dowody
    z zamówień idą pierwsze, bo są dokładniejsze (niosą klienta, okres
    i numer); umowa rozstrzyga dopiero wtedy, gdy zamówień nie ma — a nie ma
    ich często, bo rejestr zamówień jest młodszy niż współpraca, którą
    opisuje. Bez tego szczebla konsultant z umową od grudnia i pierwszym
    zamówieniem z września wyglądał jak nowa osoba (zgłoszenie 09.2026).

    Szkice u innych klientów NIE liczą się jako trwająca współpraca (szkic to
    plan, nie praca) — tak samo jak w regule „dodatkowego projektu" od 0308.
    Reguła kontynuacji u TEGO klienta (``previous_of``, okno 31 dni) zostaje
    nietknięta: szkic następnego zamówienia jest tam poprawnym poprzednikiem.
    """

    people = {fact.candidate_id for fact in entry_facts if fact.candidate_id}
    by_person: dict[int, list[OrderFact]] = {}
    if people:
        others = await load_facts(
            db,
            Contract.candidate_id.in_(sorted(people)),
            ClientOrder.status.notin_(
                (ClientOrderStatus.cancelled, ClientOrderStatus.draft)
            ),
        )
        for other in others:
            by_person.setdefault(other.candidate_id, []).append(other)
    engagements = await _prior_engagements(db, people, window)

    result: dict[int, EntryClass] = {}
    for fact in entry_facts:
        prior = (
            [
                other
                for other in by_person.get(fact.candidate_id, ())
                if other.order_id != fact.order_id and _precedes(other, fact)
            ]
            if fact.candidate_id is not None
            else []
        )

        running = [
            other
            for other in prior
            if other.client_id != fact.client_id
            and fact.start is not None
            and _runs_on(other, fact.start)
        ]
        if running:
            result[fact.order_id] = EntryClass(
                "additional_project",
                running_client_names=tuple(
                    sorted({other.client_name for other in running})
                ),
            )
            continue

        previous = previous_of(fact, siblings_of(fact, siblings))
        if previous is not None:
            result[fact.order_id] = EntryClass(
                "order_continuation",
                previous=previous,
                previous_client_name=previous.client_name,
            )
            continue

        if prior:
            # Powrót po dłuższej przerwie albo przejście od innego klienta —
            # rozstrzyga klient ostatniego wcześniejszego zamówienia osoby.
            last = max(
                prior,
                key=lambda other: (
                    other.end or other.start or date.min,
                    other.start or date.min,
                    other.order_id,
                ),
            )
            result[fact.order_id] = EntryClass(
                "order_continuation"
                if last.client_id == fact.client_id
                else "client_change",
                previous=last,
                previous_client_name=last.client_name,
            )
            continue

        entry_class = _classify_by_engagement(
            fact, engagements.get(fact.candidate_id or 0, ())
        )
        result[fact.order_id] = entry_class
    return result


def _classify_by_engagement(
    fact: OrderFact, engagements: Sequence[Engagement]
) -> EntryClass:
    """Ta sama drabinka, gdy jedynym dowodem współpracy jest umowa.

    Kolejność szczebli jest lustrem tej z zamówień: najpierw ten klient
    (kontynuacja), potem równoległa praca u innego (dodatkowy projekt),
    na końcu współpraca już zamknięta (zmiana klienta).
    """

    if not engagements:
        return EntryClass("new")

    here = [eng for eng in engagements if eng.client_id == fact.client_id]
    if here:
        first = min(eng.start for eng in here)
        return EntryClass("order_continuation", engagement_since=first)

    running = [
        eng for eng in engagements if fact.start is not None and eng.runs_on(fact.start)
    ]
    if running:
        return EntryClass(
            "additional_project",
            running_client_names=tuple(sorted({eng.client_name for eng in running})),
            engagement_since=min(eng.start for eng in running),
        )

    last = max(engagements, key=lambda eng: (eng.end or eng.start, eng.start))
    return EntryClass(
        "client_change",
        previous_client_name=last.client_name,
        engagement_since=last.start,
    )


async def _entries(
    db: AsyncSession, window: MonthWindow
) -> tuple[list[OrderEntryItem], list[OrderFact], dict[int, EntryClass]]:
    start = effective_start_expr()
    facts = await load_facts(
        db,
        ClientOrder.status != ClientOrderStatus.cancelled,
        start.is_not(None),
        start >= window.first,
        start <= window.last,
    )
    siblings = await load_siblings(db, facts)
    classes = await _classify_entries(db, facts, siblings, window)
    items = [
        OrderEntryItem(
            **_ref(fact),
            start_date=fact.start,
            end_date=fact.end,
            rate_cost=fact.rate_cost,
            rate_revenue=fact.rate_revenue,
            rate_unit=fact.rate_unit,
            currency=fact.currency,
            order_type=fact.order_type,
            status=fact.status,
        )
        for fact in facts
        if classes[fact.order_id].kind == "new"
    ]
    return sorted(items, key=_sort_key), facts, classes


# ── Zejścia i kończące się zamówienia ────────────────────────────────────────


async def _exits(
    db: AsyncSession, window: MonthWindow, today: date
) -> tuple[list[OrderExitItem], list[OrderExitItem]]:
    """Dwie listy z JEDNEGO przebiegu: zejścia i kończące się zamówienia.

    Rozdziela je werdykt: zapisana intencja zakończenia to zejście, jej brak —
    samo zamówienie dobiegające końca przy żywej współpracie. Dwa osobne
    przebiegi rozjechałyby się przy pierwszej poprawce drabinki, a wtedy ta
    sama osoba potrafiłaby stać w obu zakładkach albo w żadnej.
    """
    end = effective_end_expr()
    facts = await load_facts(
        db,
        ClientOrder.status.notin_(
            (ClientOrderStatus.cancelled, ClientOrderStatus.draft)
        ),
        end.is_not(None),
        end >= window.first,
        end <= window.last,
    )
    intents = await load_ending_intents(db, facts)
    siblings = await load_siblings(db, facts)
    # Zapisany brak rozstrzyga werdykt także wtedy, gdy zegar przeglądarki
    # i serwera mówi co innego niż dzień wykrycia — Zejścia i Braki nie mogą
    # sobie przeczyć.
    gap_orders = (
        set(
            (
                await db.scalars(
                    select(OrderGap.order_id).where(
                        OrderGap.order_id.in_([fact.order_id for fact in facts]),
                        OrderGap.status == GAP_STATUS_OPEN,
                    )
                )
            ).all()
        )
        if facts
        else set()
    )
    exits: list[OrderExitItem] = []
    ending: list[OrderExitItem] = []
    for fact in facts:
        if fact.end is None:
            continue
        intent = intents.get(fact.order_id)
        successor = successor_of(fact, siblings_of(fact, siblings))
        # Zejście = osoba od kolejnego miesiąca nie świadczy już usług. Warunek
        # liczymy z FAKTÓW, nie z napisu werdyktu: intencja zakończenia jest
        # w drabince niżej sprawdzana pierwsza, więc rzadki przypadek
        # „wypowiedzenie + żywy następca" zostawałby w Zejściach mimo tego, że
        # osoba pracuje dalej.
        if fact.works_until_md_exhausted or successor is not None:
            continue
        # Zejście = ktoś ZAPISAŁ koniec współpracy (wypowiedzenie, zamiana
        # kontraktora, decyzja DL po offboardingu MD, usunięcie z zamówienia,
        # „zostaw jako historia"). Sam koniec daty zamówienia nic o współpracy
        # nie mówi — to osobna zakładka. Decyzja Artura 20.09.2026: wszystkie
        # pięć rodzajów intencji zostaje w Zejściach.
        if intent is not None:
            verdict, label = "ended_intent", INTENT_LABELS[intent]
        elif fact.end >= today and fact.order_id not in gap_orders:
            verdict = "ending_pending"
            label = (
                f"Kończy się {_fmt_date(fact.end)} — na razie brak kolejnego zamówienia"
            )
        else:
            verdict = "no_successor"
            label = "Brak kolejnego zamówienia — do usunięcia z rozliczeń"
        bucket = exits if verdict == "ended_intent" else ending
        bucket.append(
            OrderExitItem(
                **_ref(fact),
                end_date=fact.end,
                start_date=fact.start,
                rate_cost=fact.rate_cost,
                rate_revenue=fact.rate_revenue,
                rate_unit=fact.rate_unit,
                currency=fact.currency,
                order_type=fact.order_type,
                verdict=verdict,
                verdict_label=label,
                intent=intent,
            )
        )
    return sorted(exits, key=_sort_key), sorted(ending, key=_sort_key)


# ── Zmiany ───────────────────────────────────────────────────────────────────


async def _group_refs(db: AsyncSession, group_ids: Iterable[int]) -> dict[int, dict]:
    ids = sorted(set(group_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(
            ClientOrderGroup.id,
            ClientOrderGroup.client_id,
            ClientOrderGroup.order_number,
            client_display_name_expression().label("client_name"),
            func.count(ClientOrder.id).label("lines"),
        )
        .join(Client, Client.id == ClientOrderGroup.client_id)
        .outerjoin(
            ClientOrder,
            (ClientOrder.order_group_id == ClientOrderGroup.id)
            & (ClientOrder.status != ClientOrderStatus.cancelled),
        )
        .where(ClientOrderGroup.id.in_(ids))
        .group_by(ClientOrderGroup.id, Client.id)
    )
    return {
        row.id: {
            "order_id": None,
            "order_group_id": row.id,
            "contract_id": None,
            "client_id": row.client_id,
            "client_name": row.client_name or "—",
            "consultant_name": f"Całe zamówienie ({row.lines} os.)",
            "order_number": row.order_number or "—",
        }
        for row in rows.all()
    }


async def _changes(
    db: AsyncSession,
    window: MonthWindow,
    entry_facts: list[OrderFact],
    classes: dict[int, EntryClass],
) -> list[OrderChangeItem]:
    zone = ZoneInfo(DEFAULT_TZ)
    events = list(
        (
            await db.scalars(
                select(OrderChangeEvent)
                .where(
                    OrderChangeEvent.created_at >= local_day_start(window.first),
                    OrderChangeEvent.created_at < local_day_start(window.next_first),
                )
                .order_by(
                    OrderChangeEvent.created_at.desc(), OrderChangeEvent.id.desc()
                )
            )
        ).all()
    )
    order_ids = sorted({e.order_id for e in events if e.order_id is not None})
    facts = (
        {
            fact.order_id: fact
            for fact in await load_facts(db, ClientOrder.id.in_(order_ids))
        }
        if order_ids
        else {}
    )
    groups = await _group_refs(
        db,
        (e.order_group_id for e in events if e.order_id is None and e.order_group_id),
    )
    author_ids = sorted({e.created_by_user_id for e in events if e.created_by_user_id})
    authors = (
        dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(author_ids))
                )
            ).all()
        )
        if author_ids
        else {}
    )

    items: list[OrderChangeItem] = []
    for event in events:
        if event.order_id is not None:
            fact = facts.get(event.order_id)
            if fact is None:
                continue  # zamówienie usunięte — nie ma już czego rozliczać
            ref = _ref(fact)
            whole = False
        else:
            ref = groups.get(event.order_group_id or 0)
            if ref is None:
                continue
            whole = True
        items.append(
            OrderChangeItem(
                **ref,
                kind=event.field,
                occurred_at=event.created_at,
                effective_date=event.created_at.astimezone(zone).date(),
                old_amount=event.old_amount,
                new_amount=event.new_amount,
                old_unit=event.old_unit,
                new_unit=event.new_unit,
                currency=event.currency,
                old_date=event.old_date,
                new_date=event.new_date,
                is_whole_order=whole,
                source=event.source,
                author_name=authors.get(event.created_by_user_id),
            )
        )

    # Nowe zamówienia osób, które już z nami pracują: kontynuacja u tego samego
    # klienta, przejście do innego klienta i dodatkowy projekt. To są zmiany
    # w trwającej współpracy, a nie wejścia — Finanse i tak potrzebują tu
    # nowego numeru zamówienia do faktury.
    for fact in entry_facts:
        entry_class = classes.get(fact.order_id)
        if entry_class is None or entry_class.kind == "new":
            continue
        previous = entry_class.previous
        items.append(
            OrderChangeItem(
                **_ref(fact),
                kind=entry_class.kind,
                effective_date=fact.start,
                start_date=fact.start,
                rate_cost=fact.rate_cost,
                rate_revenue=fact.rate_revenue,
                rate_unit=fact.rate_unit,
                currency=fact.currency,
                other_client_names=list(entry_class.running_client_names),
                previous_order_number=previous.number if previous else None,
                previous_end_date=previous.end if previous else None,
                previous_client_name=entry_class.previous_client_name,
                engagement_since=entry_class.engagement_since,
            )
        )

    # Najpierw alfabetycznie, potem stabilnie po dacie malejąco — wiersze
    # z dziennika i syntetyczne muszą iść jedną chronologią, a nie dwiema
    # doklejonymi do siebie listami.
    items.sort(key=_sort_key)
    items.sort(key=lambda item: item.effective_date or date.min, reverse=True)
    return items


# ── Braki ────────────────────────────────────────────────────────────────────


async def _gaps(db: AsyncSession, window: MonthWindow) -> list[OrderGapItem]:
    zone = ZoneInfo(DEFAULT_TZ)
    rows = (
        await db.execute(
            select(
                OrderGap,
                client_display_name_expression().label("client_name"),
                Candidate.name,
                Candidate.lastname,
            )
            .outerjoin(Client, Client.id == OrderGap.client_id)
            .outerjoin(Contract, Contract.id == OrderGap.contract_id)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(
                OrderGap.detected_on >= window.first,
                OrderGap.detected_on <= window.last,
            )
            # Otwarte braki (``open``) przed uzupełnionymi (``filled_late``).
            .order_by(OrderGap.status.desc(), OrderGap.detected_on.desc(), OrderGap.id)
        )
    ).all()
    items: list[OrderGapItem] = []
    for gap, client_name, first, last in rows:
        delay = None
        if gap.resolved_at is not None:
            delay = (gap.resolved_at.astimezone(zone).date() - gap.detected_on).days
        if gap.status == GAP_STATUS_FILLED_LATE and delay is not None and delay <= 0:
            # Uzupełnione w dniu wykrycia = na czas (UAT B69) — wpis zostaje
            # w bazie (pętla mogła go założyć rano), ale nie jest brakiem.
            continue
        items.append(
            OrderGapItem(
                gap_id=gap.id,
                order_id=gap.order_id,
                order_group_id=gap.order_group_id,
                contract_id=gap.contract_id,
                client_id=gap.client_id,
                client_name=client_name or "—",
                consultant_name=f"{first or ''} {last or ''}".strip() or "—",
                order_number=gap.order_number or "—",
                ended_on=gap.ended_on,
                detected_on=gap.detected_on,
                status=gap.status,
                resolved_order_number=gap.resolved_order_number,
                resolved_at=gap.resolved_at,
                delay_days=max(delay, 0) if delay is not None else None,
            )
        )
    return items


# ── Filtry ───────────────────────────────────────────────────────────────────

OrderChangesTab = Literal["changes", "entries", "exits", "ending", "gaps"]
ORDER_CHANGES_TABS: tuple[OrderChangesTab, ...] = (
    "changes",
    "entries",
    "exits",
    "ending",
    "gaps",
)


@dataclass(frozen=True)
class OrderChangesFilters:
    """Filtry widoku. Jedno źródło prawdy dla ekranu i dla eksportu."""

    query: Optional[str] = None
    client_id: Optional[int] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None

    @property
    def active(self) -> bool:
        return any(
            value is not None and value != ""
            for value in (self.query, self.client_id, self.date_from, self.date_to)
        )


_COMBINING_MARKS = re.compile("[\u0300-\u036f]")


def fold_text(value: str) -> str:
    """Bez wielkości liter i ogonków — lustro ``foldText`` z frontu.

    ``ł`` nie rozkłada się przez NFD (to osobny znak, nie „l" + ogonek), więc
    wymaga jawnej podmiany; bez niej „Malkowski" nie znajduje „Małkowski".
    """

    lowered = unicodedata.normalize("NFD", value.lower())
    return _COMBINING_MARKS.sub("", lowered).replace("ł", "l")


def _haystack(item) -> str:
    return fold_text(f"{item.consultant_name} {item.client_name} {item.order_number}")


def _filtered(
    items: Sequence,
    filters: OrderChangesFilters,
    words: tuple[str, ...],
    date_of: Callable[[object], Optional[date]],
) -> list:
    result = []
    for item in items:
        if filters.client_id is not None and item.client_id != filters.client_id:
            continue
        if words:
            haystack = _haystack(item)
            if not all(word in haystack for word in words):
                continue
        if filters.date_from is not None or filters.date_to is not None:
            # Wiersz bez daty nie mieści się w żadnym zakresie — „nie wiadomo
            # kiedy" nie może udawać trafienia.
            day = date_of(item)
            if day is None:
                continue
            if filters.date_from is not None and day < filters.date_from:
                continue
            if filters.date_to is not None and day > filters.date_to:
                continue
        result.append(item)
    return result


def apply_filters(
    response: OrderChangesResponse, filters: OrderChangesFilters
) -> OrderChangesResponse:
    """Zawęża wszystkie listy i przelicza liczniki.

    Data znaczy w każdej zakładce co innego: w Zmianach to dzień zmiany,
    w Wejściach start, w Zejściach i Kończących się zamówieniach koniec,
    a w Brakach dzień wykrycia braku.
    """

    if not filters.active:
        return response
    words = tuple(fold_text(filters.query).split()) if filters.query else ()
    changes = _filtered(response.changes, filters, words, lambda i: i.effective_date)
    entries = _filtered(response.entries, filters, words, lambda i: i.start_date)
    exits = _filtered(response.exits, filters, words, lambda i: i.end_date)
    ending = _filtered(response.ending_orders, filters, words, lambda i: i.end_date)
    gaps = _filtered(response.gaps, filters, words, lambda i: i.detected_on)
    return response.model_copy(
        update={
            "changes": changes,
            "entries": entries,
            "exits": exits,
            "ending_orders": ending,
            "gaps": gaps,
            "counts": OrderChangesCounts(
                changes=len(changes),
                entries=len(entries),
                exits=len(exits),
                ending=len(ending),
                gaps=len(gaps),
            ),
        }
    )


async def build_order_changes(
    db: AsyncSession,
    year: int,
    month: int,
    *,
    today: Optional[date] = None,
    filters: Optional[OrderChangesFilters] = None,
) -> OrderChangesResponse:
    window = MonthWindow.of(year, month)
    day = today or business_today()
    entries, entry_facts, classes = await _entries(db, window)
    exits, ending = await _exits(db, window, day)
    changes = await _changes(db, window, entry_facts, classes)
    gaps = await _gaps(db, window)
    tracked_since = await db.scalar(select(func.min(OrderChangeEvent.created_at)))
    open_total = await db.scalar(
        select(func.count(OrderGap.id)).where(OrderGap.status == GAP_STATUS_OPEN)
    )
    response = OrderChangesResponse(
        period=OrderChangesPeriod(
            year=year, month=month, label=period_label(year, month)
        ),
        counts=OrderChangesCounts(
            changes=len(changes),
            entries=len(entries),
            exits=len(exits),
            ending=len(ending),
            gaps=len(gaps),
        ),
        changes=changes,
        entries=entries,
        exits=exits,
        ending_orders=ending,
        gaps=gaps,
        changes_tracked_since=tracked_since,
        gaps_tracked_since=settings.ORDER_GAP_TRACKING_START,
        # Baner o całej historii — celowo nie zawężany filtrami widoku.
        open_gaps_total=open_total or 0,
    )
    return apply_filters(response, filters) if filters else response


# ── Eksport ──────────────────────────────────────────────────────────────────


def _rate(
    amount: Optional[Decimal], unit: Optional[str], currency: Optional[str]
) -> str:
    if amount is None:
        return "—"
    unit_label = UNIT_LABELS.get(unit or "", unit or "")
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + (
        f" {currency or 'PLN'}/{unit_label}" if unit_label else f" {currency or 'PLN'}"
    )


def _new_order_value(item: OrderChangeItem) -> str:
    """BEZ klienta i numeru zamówienia — te mają w arkuszu własne kolumny."""

    return (
        f"od {_fmt_date(item.effective_date)}; koszt "
        f"{_rate(item.rate_cost, item.rate_unit, item.currency)}, przychód "
        f"{_rate(item.rate_revenue, item.rate_unit, item.currency)}"
    )


def _previous_order_label(item: OrderChangeItem) -> str:
    """Skąd wiadomo, że współpraca już trwała.

    Poprzednie zamówienie, a gdy go w NEXUSIE nie ma — data startu umowy.
    Puste „—" czytałoby się jak utrata danych, nie jak inny rodzaj dowodu.
    """

    if item.previous_order_number:
        return f"zam. {item.previous_order_number} (do {_fmt_date(item.previous_end_date)})"
    if item.engagement_since:
        return f"współpraca od {_fmt_date(item.engagement_since)}"
    return "—"


def _change_description(item: OrderChangeItem) -> tuple[str, str, str]:
    if item.kind == "additional_project":
        return (
            "Dodatkowy projekt",
            "u: " + ", ".join(item.other_client_names),
            _new_order_value(item),
        )
    if item.kind == "order_continuation":
        return (
            "Kontynuacja zamówienia",
            _previous_order_label(item),
            _new_order_value(item),
        )
    if item.kind == "client_change":
        return (
            "Zmiana klienta",
            f"{item.previous_client_name or '—'} · {_previous_order_label(item)}",
            _new_order_value(item),
        )
    if item.kind == "end_date":
        return (
            "Zmiana daty końca",
            _fmt_date(item.old_date) if item.old_date else "bezterminowo",
            _fmt_date(item.new_date) if item.new_date else "bezterminowo",
        )
    label = (
        "Zmiana stawki kosztowej"
        if item.kind == "rate_cost"
        else "Zmiana stawki przychodowej"
    )
    return (
        label,
        _rate(item.old_amount, item.old_unit, item.currency),
        _rate(item.new_amount, item.new_unit, item.currency),
    )


def _sheet(
    workbook: Workbook,
    title: str,
    headers: list[str],
    rows: list[list[object]],
    widths: list[int],
) -> None:
    sheet = workbook.create_sheet(title)
    sheet.append(headers)
    fill = PatternFill("solid", fgColor="1F4E78")
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = fill
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        sheet.append(
            [_safe_text(value) if isinstance(value, str) else value for value in row]
        )
    for index, width in enumerate(widths, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            if isinstance(cell.value, bool):
                continue
            if isinstance(cell.value, (float, Decimal)):
                cell.number_format = "#,##0.00"
            elif isinstance(cell.value, int):
                cell.number_format = "0"
            elif isinstance(cell.value, date):
                cell.number_format = "DD.MM.YYYY"
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False


def _exit_like_sheet(
    workbook: Workbook, title: str, items: Sequence[OrderExitItem]
) -> None:
    """Zejścia i Kończące się zamówienia dzielą wiersz, więc i kolumny.

    Tytuł arkusza musi się zmieścić w 31 znakach Excela — stąd skrót „zam."
    zamiast pełnej nazwy zakładki.
    """

    _sheet(
        workbook,
        title,
        [
            "Konsultant",
            "Klient",
            "Numer zamówienia",
            "Data zakończenia",
            "Typ zamówienia",
            "Decyzja dla rozliczeń",
        ],
        [
            [
                item.consultant_name,
                item.client_name,
                item.order_number,
                item.end_date,
                ORDER_TYPE_LABELS.get(item.order_type, item.order_type),
                item.verdict_label,
            ]
            for item in items
        ],
        [28, 28, 22, 16, 15, 60],
    )


def build_order_changes_workbook(
    data: OrderChangesResponse,
    tabs: Optional[Sequence[OrderChangesTab]] = None,
) -> bytes:
    """Eksport zakładek. ``tabs`` puste — cały audyt, jak dotąd.

    Dane muszą przyjść z ``build_order_changes`` z TYMI SAMYMI filtrami, które
    ma na sobie ekran — plik ma zawierać dokładnie to, co użytkownik widzi.
    """

    wanted = set(tabs) if tabs else set(ORDER_CHANGES_TABS)
    workbook = Workbook()
    workbook.remove(workbook.active)
    zone = ZoneInfo(DEFAULT_TZ)

    if "changes" in wanted:
        _sheet(
            workbook,
            f"Zmiany ({data.counts.changes})",
            [
                "Konsultant",
                "Klient",
                "Numer zamówienia",
                "Zmiana",
                "Było",
                "Jest",
                "Data",
                "Autor",
            ],
            [
                [
                    item.consultant_name,
                    item.client_name,
                    item.order_number,
                    *_change_description(item),
                    item.occurred_at.astimezone(zone).replace(tzinfo=None)
                    if item.occurred_at
                    else item.effective_date,
                    item.author_name or ("System" if item.source == "system" else "—"),
                ]
                for item in data.changes
            ],
            [28, 28, 22, 26, 34, 46, 18, 22],
        )
    if "entries" in wanted:
        _sheet(
            workbook,
            f"Wejścia ({data.counts.entries})",
            [
                "Konsultant",
                "Klient",
                "Numer zamówienia",
                "Data rozpoczęcia",
                "Data zakończenia",
                "Stawka kosztowa",
                "Stawka przychodowa",
                "Jednostka",
                "Waluta",
                "Typ zamówienia",
                "Status",
            ],
            [
                [
                    item.consultant_name,
                    item.client_name,
                    item.order_number,
                    item.start_date,
                    item.end_date,
                    item.rate_cost,
                    item.rate_revenue,
                    UNIT_LABELS.get(item.rate_unit or "", item.rate_unit or ""),
                    item.currency or "PLN",
                    ORDER_TYPE_LABELS.get(item.order_type, item.order_type),
                    "Szkic" if item.status == ClientOrderStatus.draft.value else "",
                ]
                for item in data.entries
            ],
            [28, 28, 22, 16, 16, 16, 18, 11, 9, 15, 10],
        )
    if "exits" in wanted:
        _exit_like_sheet(workbook, f"Zejścia ({data.counts.exits})", data.exits)
    if "ending" in wanted:
        _exit_like_sheet(
            workbook,
            f"Kończące się zam. ({data.counts.ending})",
            data.ending_orders,
        )
    if "gaps" in wanted:
        _sheet(
            workbook,
            f"Braki ({data.counts.gaps})",
            [
                "Konsultant",
                "Klient",
                "Zakończone zamówienie",
                "Koniec zamówienia",
                "Brak od",
                "Status",
                "Uzupełnione zamówieniem",
                "Uzupełniono",
                "Opóźnienie (dni)",
            ],
            [
                [
                    item.consultant_name,
                    item.client_name,
                    item.order_number,
                    item.ended_on,
                    item.detected_on,
                    "Uzupełnione z opóźnieniem"
                    if item.status == "filled_late"
                    else "Brak zamówienia",
                    item.resolved_order_number or "",
                    item.resolved_at.astimezone(zone).date()
                    if item.resolved_at
                    else None,
                    item.delay_days,
                ]
                for item in data.gaps
            ],
            [28, 28, 22, 18, 14, 26, 24, 14, 16],
        )
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


TAB_FILENAMES: dict[str, str] = {
    "changes": "Zmiany",
    "entries": "Wejscia",
    "exits": "Zejscia",
    "ending": "Konczace_sie_zamowienia",
    "gaps": "Braki",
}


def order_changes_filename(
    year: int, month: int, tab: Optional[OrderChangesTab] = None
) -> str:
    suffix = f"_{TAB_FILENAMES[tab]}" if tab else ""
    return f"Zmiany_w_zamowieniach{suffix}_{year}-{month:02d}.xlsx"
