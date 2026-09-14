"""Dwukierunkowa synchronizacja kontraktu z zamówieniami tej osoby (09.2026).

Zgłoszenie: kontrakt Bartosza Czapelki (Alior) stał jako „Szkic" ze stawką
kosztową 120 zł/h, bez stawki przychodowej i bez okresu zamówienia, choć jego
zamówienie OIT/0189/2026/ITVM miało już okres 15.09–31.12.2026 i stawkę
1340 PLN/MD. Kontrakt i zamówienia żyły obok siebie: zmiana w jednym miejscu
nie przechodziła do drugiego.

Podział odpowiedzialności — każda strona jest źródłem prawdy dla SWOICH pól:

* **zamówienie → kontrakt**: okres zamówienia (osobne pole
  ``client_order_start_date``/``client_order_end_date`` — NIGDY okres umowy),
  stawka przychodowa (krok harmonogramu ``client_rate_schedule`` od daty startu
  zamówienia, więc przyszła stawka zaczyna obowiązywać dopiero w swoim dniu)
  i jednostka (kontrakt „trzyma się" jednostki najnowszego zamówienia);
* **kontrakt → zamówienie**: stawka kosztowa. Kontrakt jest jej jedynym
  źródłem — wartość wpisana ręcznie w zamówieniu przegrywa przy najbliższej
  synchronizacji. Zamówienie niesie jedną liczbę, a kontrakt harmonogram,
  więc zamówienie dostaje stawkę obowiązującą NA DZIŚ (przyciętą do okresu
  zamówienia), a codzienny przebieg (``run_daily_order_cost_sync``) wprowadza
  każdą zaplanowaną podwyżkę dokładnie w jej dniu — ile by ich nie było.
  Poza zakresem: linie zamówień zbiorczych MD/kosztowych — tam stawkę kosztową
  prowadzi per linia Delivery Lead (patrz ``sync_orders_cost_from_contract``).

Przelicznik: 1 MD = 8 godzin (``order_rate_snapshots.convert_order_rate``).

Kiedy liczy się zamówienie jako „uzupełnione": ma datę rozpoczęcia i dodatnią
stawkę przychodową, a jego status nie jest ``cancelled``. Auto-szkic zakładany
przy podpisie umowy ma start skopiowany z kontraktu i PUSTĄ stawkę klienta —
bez warunku na stawkę zaślepka udawałaby okres zamówienia „od startu umowy,
bezterminowo".

Punkty wejścia:

* :func:`sync_pending_order_contracts` — wołane przed commitem każdego zapisu
  zamówienia (``order_write_errors.commit_order_write`` i usługi tła). Zbiera
  kontrakty z listenera ``after_flush``, więc nowy writer nie musi pamiętać,
  który kontrakt ruszył.
* :func:`resync_contract` — pełny przebieg dla jednego kontraktu.
* :func:`sync_orders_cost_from_contract` — sam kierunek kosztowy (zapis
  kontraktu, przebieg dobowy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from itertools import chain
from typing import Iterable, Optional, Sequence

from sqlalchemy import event, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_client_rate import ContractClientRate
from app.services.contract_lifecycle import auto_activate_complete_draft
from app.services.order_rate_snapshots import RATE_SCALE, convert_order_rate

logger = logging.getLogger(__name__)

__all__ = [
    "COST_TARGET_ORDER_STATUSES",
    "ContractSyncOutcome",
    "apply_manual_client_rate",
    "backfill_missing_order_periods",
    "OrderRevenueTerms",
    "REPAIR_MARKER",
    "SOURCE_ORDER_STATUSES",
    "convert_rate_between",
    "cost_reference_day",
    "order_revenue_terms",
    "resync_contract",
    "resync_contract_safely",
    "sync_enabled",
    "run_daily_order_cost_sync",
    "sync_contract_from_orders",
    "sync_orders_cost_from_contract",
    "sync_pending_order_contracts",
]

# Marker jednorazowej korekty (``contract_order_sync_repair``). Przebieg dobowy
# rusza DOPIERO po nim: korekta zapisuje migawkę raportu zgodności sprzed
# wdrożenia, a codzienne nadpisanie kosztów przed migawką skasowałoby dokładnie
# te niezgodności, które raport ma pokazać.
REPAIR_MARKER = "0304_contract_order_sync_repair"

# Zamówienia, z których kontrakt bierze okres i stawkę przychodową. Zakończone
# ZOSTAJĄ: opisują historię stawek (krok sprzed obecnego zamówienia).
SOURCE_ORDER_STATUSES = frozenset(
    {
        ClientOrderStatus.draft,
        ClientOrderStatus.active,
        ClientOrderStatus.paused,
        ClientOrderStatus.completed,
    }
)
# Zamówienia, którym kontrakt ustawia stawkę kosztową. Zakończone są zapisem
# tego, co rozliczono — synchronizacja od dnia wdrożenia ich nie przepisuje.
COST_TARGET_ORDER_STATUSES = frozenset(
    {
        ClientOrderStatus.draft,
        ClientOrderStatus.active,
        ClientOrderStatus.paused,
    }
)

_MONEY_2 = Decimal("0.01")
_PENDING_KEY = "contract_order_sync.pending_contract_ids"
_SKIP_KEY = "contract_order_sync.skip_contract_ids"


def skip_sync_for_contract(db: AsyncSession, contract_id: int) -> None:
    """Nie synchronizuj tego kontraktu przy najbliższym zapisie zamówień.

    Zapis historyczny na zamówieniu (osoba z ZAKOŃCZONĄ współpracą, ticket
    09.2026) opisuje przeszłość — nie może przestawić zakończonemu kontraktowi
    jednostki, dopisać mu kroku przychodu po dacie zakończenia ani okresu
    zamówienia późniejszego niż umowa.
    """
    db.info.setdefault(_SKIP_KEY, set()).add(contract_id)


_SCHEDULES = (
    "candidate_rate_schedule",
    "client_rate_schedule",
    "framework_rate_schedule",
)


# ── Arytmetyka jednostek ────────────────────────────────────────────────────


def convert_rate_between(
    value: object,
    from_unit: RateUnit,
    to_unit: RateUnit,
    *,
    from_hours: int = 160,
    to_hours: int = 160,
) -> Optional[Decimal]:
    """Przelicz stawkę między jednostkami dwóch RÓŻNYCH dokumentów.

    Godzina ↔ MD to zawsze 8 (ticket: „1 MD = 8 godzin"), MD ↔ miesiąc to 22.
    Godzina ↔ miesiąc zależy od liczby godzin rozliczeniowych — i to jest
    jedyny powód tej funkcji: przy przejściu między kontraktem a zamówieniem
    liczba godzin miesiąca należy do strony, która jest MIESIĘCZNA, a nie do
    wołającego. ``convert_order_rate`` przyjmuje jedną liczbę godzin, bo
    przelicza w obrębie jednego zamówienia.
    """
    if value is None:
        return None
    source, target = RateUnit(from_unit), RateUnit(to_unit)
    hours = from_hours if source == RateUnit.monthly else to_hours
    return convert_order_rate(value, source, target, hours or 160)


def _q2(value: Optional[Decimal]) -> Optional[Decimal]:
    return None if value is None else value.quantize(_MONEY_2, ROUND_HALF_UP)


def _dec(value: object) -> Optional[Decimal]:
    if value is None:
        return None
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _same_amount(left: object, right: object) -> bool:
    a, b = _dec(left), _dec(right)
    if a is None or b is None:
        return a is None and b is None
    return a.quantize(RATE_SCALE) == b.quantize(RATE_SCALE)


# ── Warunki zamówienia widziane przez kontrakt ──────────────────────────────


@dataclass(frozen=True)
class OrderRevenueTerms:
    """Okres i stawka przychodowa „uzupełnionego" zamówienia."""

    order_id: int
    start: date
    end: Optional[date]
    rate: Decimal
    unit: RateUnit
    currency: str
    billing_hours: int


def order_revenue_terms(order: ClientOrder) -> Optional[OrderRevenueTerms]:
    """Warunki, które zamówienie narzuca kontraktowi — albo ``None``.

    Linia zamówienia grupowego (MD/kosztowego) jest zawsze w PLN/MD po stronie
    kanonicznej (``md_rate_revenue``), a ``rate_client`` niesie tę samą stawkę
    w walucie linii — tej używamy, gdy jest, bo kontrakt ma własną walutę.
    """
    status = ClientOrderStatus(order.status)
    if status not in SOURCE_ORDER_STATUSES or order.start_date is None:
        return None
    if order.order_group_id is not None:
        if order.rate_client is not None:
            rate = order.rate_client
            currency = order.rate_client_currency or order.currency or "PLN"
        elif order.md_rate_revenue is not None:
            rate, currency = order.md_rate_revenue, "PLN"
        else:
            return None
        unit = RateUnit.daily
    else:
        if order.rate_client is None:
            return None
        rate = order.rate_client
        currency = order.rate_client_currency or order.currency or "PLN"
        unit = RateUnit(order.rate_unit)
    amount = _dec(rate)
    if amount is None or amount <= 0:
        return None
    return OrderRevenueTerms(
        order_id=order.id,
        start=order.start_date,
        end=order.end_date,
        rate=amount,
        unit=unit,
        currency=str(currency).strip().upper() or "PLN",
        billing_hours=order.billing_hours_per_month or 160,
    )


def _latest(terms: Sequence[OrderRevenueTerms]) -> OrderRevenueTerms:
    """Najnowsze zamówienie = najpóźniejszy start; remis rozstrzyga nowszy wiersz."""
    return max(terms, key=lambda t: (t.start, t.order_id))


def cost_reference_day(order: ClientOrder, today: date) -> date:
    """Dzień, którego stawkę kosztową zamówienie ma nieść: dziś w granicach okresu.

    Zamówienie przyszłe dostaje stawkę ze swojego pierwszego dnia (a nie
    dzisiejszą — podwyżka od 01.10 musi być w zamówieniu od 01.10), zamówienie
    przeterminowane — z ostatniego.
    """
    day = today
    if order.start_date is not None and day < order.start_date:
        day = order.start_date
    if order.end_date is not None and day > order.end_date:
        day = order.end_date
    return day


# ── Wynik ────────────────────────────────────────────────────────────────────


@dataclass
class ContractSyncOutcome:
    contract_id: int
    unit_switched_from: Optional[str] = None
    unit_switched_to: Optional[str] = None
    revenue_steps_changed: int = 0
    period_changed: bool = False
    currency_changed: bool = False
    activated: bool = False
    order_cost_ids: list[int] = field(default_factory=list)
    source_order_id: Optional[int] = None

    @property
    def changed(self) -> bool:
        return bool(
            self.unit_switched_to
            or self.revenue_steps_changed
            or self.period_changed
            or self.currency_changed
            or self.activated
            or self.order_cost_ids
        )

    def as_details(self) -> dict:
        details: dict = {"source_order_id": self.source_order_id}
        if self.unit_switched_to:
            details["rate_unit"] = {
                "from": self.unit_switched_from,
                "to": self.unit_switched_to,
            }
        if self.revenue_steps_changed:
            details["revenue_steps_changed"] = self.revenue_steps_changed
        if self.period_changed:
            details["order_period_changed"] = True
        if self.currency_changed:
            details["rate_client_currency_changed"] = True
        if self.activated:
            details["auto_activated"] = True
        if self.order_cost_ids:
            details["order_cost_synced"] = sorted(self.order_cost_ids)
        return details


# ── Zamówienie → kontrakt ────────────────────────────────────────────────────


def _switch_contract_unit(contract: Contract, target: RateUnit) -> None:
    """Przestaw jednostkę kontraktu, przeliczając KAŻDĄ kwotę, którą ona opisuje.

    ``rate_unit`` rządzi obiema stawkami, harmonogramami, stawką ramową
    i widełkami. Zmiana samej jednostki bez przeliczenia zamieniłaby 120 zł/h
    w 120 zł/MD — cichy, ośmiokrotny błąd marży.
    """
    source = RateUnit(contract.rate_unit)
    if source == target:
        return
    hours = contract.billing_hours_per_month or 160

    def conv(value: object) -> Optional[Decimal]:
        return convert_order_rate(value, source, target, hours)

    contract.rate_candidate = conv(contract.rate_candidate)
    contract.rate_client = conv(contract.rate_client)
    contract.framework_rate = _q2(conv(contract.framework_rate))
    contract.target_rate_min = _q2(conv(contract.target_rate_min))
    contract.target_rate_max = _q2(conv(contract.target_rate_max))
    for step in contract.candidate_rate_schedule:
        step.rate = conv(step.rate)
    for step in contract.client_rate_schedule:
        step.rate = conv(step.rate)
    for step in contract.framework_rate_schedule:
        step.rate = _q2(conv(step.rate))
    contract.rate_unit = target


def _refresh_rate_caches(contract: Contract, today: date) -> None:
    """Odśwież cache ``rate_client`` — jedyną stawkę, którą ta ścieżka zmienia.

    Kolumna jest cache'em kroku obowiązującego dziś (patrz ``contract_rates``).
    Cache stawki kosztowej zostaje nietknięty: zamówienie nie jest jej źródłem,
    a ``_switch_contract_unit`` przelicza go sam przy zmianie jednostki.
    """
    if contract.client_rate_schedule:
        contract.rate_client = contract.effective_client_rate(today)
    contract.margin = contract.calculate_margin()


def _period_projected_from_dead_order(
    contract: Contract, orders: Sequence[ClientOrder]
) -> bool:
    """Czy okres zamówienia na kontrakcie to dokładnie okres zamówienia, które
    przestało być źródłem (anulowane). Okres wpisany ręcznie zwykle nie
    pokrywa się z żadnym zamówieniem co do dnia, więc zostaje."""
    start = contract.client_order_start_date
    if start is None:
        return False
    return any(
        order.client_id == contract.client_id
        and order.start_date == start
        and order.end_date == contract.client_order_end_date
        and ClientOrderStatus(order.status) not in SOURCE_ORDER_STATUSES
        for order in orders
    )


async def sync_contract_from_orders(
    db: AsyncSession,
    contract: Contract,
    orders: Iterable[ClientOrder],
    *,
    actor_id: Optional[int],
    today: date,
    auto_activate: bool = True,
    follow_order_unit: bool = True,
    follow_order_currency: bool = True,
) -> ContractSyncOutcome:
    """Przenieś na kontrakt okres, jednostkę i stawkę przychodową z zamówień.

    Wymaga wczytanych harmonogramów kontraktu. Idempotentne: drugi przebieg
    na tych samych danych nic nie zmienia. ``follow_order_unit=False`` dla
    zapisu, w którym operator JAWNIE wybrał jednostkę kontraktu — wtedy stawka
    z zamówienia jest przeliczana na jego wybór, a nie odwrotnie.
    """
    outcome = ContractSyncOutcome(contract_id=contract.id)
    if contract.status == ContractStatus.void:
        return outcome
    orders = list(orders)

    terms = [
        t
        for order in orders
        if order.client_id == contract.client_id
        and (t := order_revenue_terms(order)) is not None
    ]
    schedule = contract.client_rate_schedule
    order_steps: dict[int, ContractClientRate] = {}
    for step in list(schedule):
        if step.source_order_id is None:
            continue
        if step.source_order_id in order_steps:
            # Dwa kroki z jednego zamówienia to pozostałość po wyścigu —
            # zostaje jeden, bo rozstrzygnięcie i tak brałoby ostatni.
            schedule.remove(order_steps[step.source_order_id])
            outcome.revenue_steps_changed += 1
        order_steps[step.source_order_id] = step

    if not terms:
        if not order_steps and _period_projected_from_dead_order(contract, orders):
            # Okres uzupełniony nocnym przebiegiem nie ma kroku stawki, więc
            # gałąź niżej go nie zobaczy. Pokrywa się co do dnia z zamówieniem,
            # które już nie obowiązuje — nie udaje, że klient ma zamówienie.
            contract.client_order_start_date = None
            contract.client_order_end_date = None
            outcome.period_changed = True
        if order_steps:
            # Zamówienie, z którego pochodziła stawka, zostało anulowane albo
            # skasowane. Krok znika, a okres (prowadzony przez synchronizację)
            # przestaje udawać, że ktoś tu ma zamówienie.
            for step in order_steps.values():
                schedule.remove(step)
            outcome.revenue_steps_changed += len(order_steps)
            if contract.client_order_start_date or contract.client_order_end_date:
                contract.client_order_start_date = None
                contract.client_order_end_date = None
                outcome.period_changed = True
            _refresh_rate_caches(contract, today)
        return outcome

    latest = _latest(terms)
    outcome.source_order_id = latest.order_id
    # Przychód, który NIE pochodzi z zamówień: stawka w kolumnie bez
    # harmonogramu albo krok ręczny/z aneksu. Liczony PRZED krokiem 1, który
    # z takiej kolumny robi krok bazowy.
    has_own_revenue = any(step.source_order_id is None for step in schedule) or (
        not schedule and contract.rate_client is not None
    )

    # 1. Stawka przychodowa wpisana kiedyś wprost w kolumnę (bez harmonogramu)
    #    nie może zniknąć z historii: pierwszy krok z zamówienia przejąłby
    #    wszystkie wcześniejsze miesiące. Zostaje jako krok od startu umowy.
    if not schedule and contract.rate_client is not None:
        first_order_start = min(t.start for t in terms)
        if contract.start_date is not None and contract.start_date < first_order_start:
            schedule.append(
                ContractClientRate(
                    rate=contract.rate_client,
                    effective_from=contract.start_date,
                    note="Stawka sprzed synchronizacji z zamówieniami",
                    created_by=actor_id,
                )
            )

    # 2. Jednostka: kontrakt „trzyma się" jednostki najnowszego zamówienia.
    #    Świeży kontrakt z umowy B2B jest godzinowy; pierwsze zamówienie w MD
    #    przestawia go na MD (120 zł/h → 960 zł/MD) i tak zostaje, dopóki nie
    #    przyjdzie zamówienie w innej jednostce.
    if follow_order_unit and RateUnit(contract.rate_unit) != latest.unit:
        outcome.unit_switched_from = RateUnit(contract.rate_unit).value
        _switch_contract_unit(contract, latest.unit)
        outcome.unit_switched_to = latest.unit.value

    # 3. Waluta stawki przychodowej — jedna na kontrakt, więc z najnowszego
    #    zamówienia. Kroki w innej walucie nie wchodzą do harmonogramu:
    #    liczba bez waluty, w której ją podpisano, byłaby inną kwotą.
    #    Jawnie wybrana w tym samym zapisie waluta kontraktu wygrywa — wtedy do
    #    harmonogramu wchodzą tylko zamówienia w tej walucie. Waluty NIE
    #    zmieniamy też wtedy, gdy kontrakt ma przychód spoza zamówień: kroki
    #    nie niosą własnej waluty, więc 1000 PLN/MD sprzed zmiany czytałoby
    #    się po niej jako 1000 EUR/MD.
    target_currency = latest.currency
    keep_currency = not follow_order_currency or (
        has_own_revenue and contract.resolved_rate_client_currency != latest.currency
    )
    if keep_currency:
        target_currency = contract.resolved_rate_client_currency
    elif (contract.rate_client_currency or "").upper() != latest.currency or (
        (contract.currency or "").upper() != latest.currency
    ):
        contract.rate_client_currency = latest.currency
        contract.currency = latest.currency
        outcome.currency_changed = True

    contract_unit = RateUnit(contract.rate_unit)
    contract_hours = contract.billing_hours_per_month or 160
    wanted: dict[int, tuple[date, Decimal]] = {}
    for t in terms:
        if t.currency != target_currency:
            continue
        wanted[t.order_id] = (
            t.start,
            convert_rate_between(
                t.rate,
                t.unit,
                contract_unit,
                from_hours=t.billing_hours,
                to_hours=contract_hours,
            ),
        )

    # 4. Kroki harmonogramu: jeden na zamówienie, od jego daty startu. Stawka
    #    przyszłego zamówienia (130 zł od 01.10) obowiązuje więc w kontrakcie
    #    dopiero od 01.10 — resolver czyta krok właściwy dla dnia.
    for order_id, step in order_steps.items():
        if order_id not in wanted:
            schedule.remove(step)
            outcome.revenue_steps_changed += 1
    for order_id, (start, rate) in sorted(wanted.items(), key=lambda kv: kv[1][0]):
        step = order_steps.get(order_id)
        if step is None:
            schedule.append(
                ContractClientRate(
                    rate=rate,
                    effective_from=start,
                    source_order_id=order_id,
                    note="Z zamówienia klienta",
                    created_by=actor_id,
                )
            )
            outcome.revenue_steps_changed += 1
        elif step.effective_from != start or not _same_amount(step.rate, rate):
            step.effective_from = start
            step.rate = rate
            outcome.revenue_steps_changed += 1

    # 5. Okres zamówienia — osobne pole; kolejne zamówienie nadpisuje poprzednie.
    if (contract.client_order_start_date, contract.client_order_end_date) != (
        latest.start,
        latest.end,
    ):
        contract.client_order_start_date = latest.start
        contract.client_order_end_date = latest.end
        outcome.period_changed = True

    _refresh_rate_caches(contract, today)

    # 6. Szkic, który po uzupełnieniu zamówienia ma komplet danych, przestaje
    #    być szkicem — przez tę samą bramkę co ręczna aktywacja.
    #    Szkic, którego umowa już się skończyła, NIE jest aktywowany —
    #    zamówienie nie jest dowodem, że ta współpraca trwa (to rola
    #    ``sync_contract_to_live_order`` dla kontraktów zakończonych).
    if (
        auto_activate
        and contract.status == ContractStatus.draft
        and (contract.end_date is None or contract.end_date >= today)
    ):
        outcome.activated = await auto_activate_complete_draft(
            db, contract, actor_id=actor_id, status_explicit=False
        )
    return outcome


def apply_manual_client_rate(
    contract: Contract,
    rate: object,
    *,
    actor_id: Optional[int],
    today: date,
) -> bool:
    """Ręczna zmiana stawki przychodowej w kontrakcie prowadzonym harmonogramem.

    Gdy harmonogram istnieje (a po synchronizacji z zamówieniami istnieje
    prawie zawsze), resolver NIE czyta kolumny ``rate_client`` — sam zapis
    kolumny byłby cichym no-opem: 200, a pieniądze bez zmian. Zmiana dopisuje
    więc krok ręczny od dziś (ten sam wzorzec co aneks ``rate_change``);
    kolejne zamówienie z późniejszym startem przejmie stawkę od swojej daty.
    Zwraca True, gdy krok dopisano/poprawiono.
    """
    amount = _dec(rate)
    schedule = contract.client_rate_schedule
    if amount is None or not schedule:
        return False
    # Formularz kontraktu wysyła całą stawkę także wtedy, gdy nikt jej nie
    # ruszał. Krok z NIEZMIENIONĄ wartością przykryłby od dziś późniejszą
    # korektę stawki w zamówieniu — więc zapis tylko przy realnej zmianie.
    if _same_amount(contract.effective_client_rate(today), amount):
        return False
    same_day = [
        step
        for step in schedule
        if step.effective_from == today and step.source_order_id is None
    ]
    if same_day:
        same_day[-1].rate = amount
    else:
        schedule.append(
            ContractClientRate(
                rate=amount,
                effective_from=today,
                note="Zmiana stawki w kontrakcie",
                created_by=actor_id,
            )
        )
    return True


# ── Kontrakt → zamówienie ────────────────────────────────────────────────────


def _has_cost(contract: Contract) -> bool:
    return contract.rate_candidate is not None or bool(contract.candidate_rate_schedule)


async def sync_orders_cost_from_contract(
    db: AsyncSession,
    contract: Contract,
    orders: Iterable[ClientOrder],
    *,
    today: date,
) -> list[int]:
    """Ustaw zamówieniom stawkę kosztową z kontraktu. Zwraca id zmienionych.

    Kontrakt bez stawki kosztowej niczego nie nadpisuje — pusty kontrakt nie
    jest „źródłem prawdy", tylko brakiem danych. Wymaga wczytanego
    ``candidate_rate_schedule``.

    Linie zamówień ZBIORCZYCH (MD/kosztowych, ``order_group_id``) są poza
    zakresem świadomie: ich stawkę kosztową prowadzi per linia Delivery Lead
    (osobna decyzja produktowa, patrz CLAUDE.md „Zamówienia wielo-
    konsultantowe"), a kontrakty tych osób bywają szkicami z obsady bez
    stawki albo z wartością sprzed lat. Nadpisanie linii kontraktem przestawiłoby
    rozliczenia BIK/Polkomtela/BNP pierwszej nocy po wdrożeniu.
    """
    if contract.status == ContractStatus.void or not _has_cost(contract):
        return []

    contract_unit = RateUnit(contract.rate_unit)
    contract_hours = contract.billing_hours_per_month or 160
    currency = contract.resolved_rate_candidate_currency
    changed: list[int] = []
    for order in orders:
        if order.client_id != contract.client_id or order.order_group_id is not None:
            continue
        if ClientOrderStatus(order.status) not in COST_TARGET_ORDER_STATUSES:
            continue
        cost = contract.effective_candidate_rate(cost_reference_day(order, today))
        if cost is None:
            continue
        touched = False
        new_rate = convert_rate_between(
            cost,
            contract_unit,
            RateUnit(order.rate_unit),
            from_hours=contract_hours,
            to_hours=order.billing_hours_per_month or 160,
        )
        if not _same_amount(order.rate_candidate, new_rate):
            order.rate_candidate = new_rate
            touched = True
        if (order.rate_candidate_currency or "").upper() != currency:
            order.rate_candidate_currency = currency
            touched = True
        if touched:
            changed.append(order.id)
    return changed


# ── Orkiestracja ─────────────────────────────────────────────────────────────


async def _load_orders(db: AsyncSession, contract_id: int) -> list[ClientOrder]:
    return list(
        (
            await db.scalars(
                select(ClientOrder)
                .where(ClientOrder.contract_id == contract_id)
                .order_by(ClientOrder.id)
            )
        ).all()
    )


async def resync_contract(
    db: AsyncSession,
    contract: Contract | int,
    *,
    actor_id: Optional[int],
    today: Optional[date] = None,
    auto_activate: bool = True,
    follow_order_unit: bool = True,
    follow_order_currency: bool = True,
    audit: bool = True,
) -> Optional[ContractSyncOutcome]:
    """Pełny przebieg dla jednego kontraktu: zamówienia → kontrakt → zamówienia.

    Kolejność jest nośna: najpierw jednostka i stawka przychodowa z zamówień,
    potem koszt z kontraktu — już w jednostce, na którą kontrakt się przestawił.
    """
    today = today or business_today()
    contract_id = contract if isinstance(contract, int) else contract.id
    await db.flush()
    locked = await db.scalar(
        select(Contract.id).where(Contract.id == contract_id).with_for_update()
    )
    if locked is None:
        return None
    entity = contract if isinstance(contract, Contract) else None
    if entity is None:
        entity = await db.get(Contract, contract_id)
    if entity is None:
        return None
    # Zawsze ze świeżej bazy: skasowane zamówienie zabrało swój krok stawki
    # kaskadą w bazie, a stara kolekcja w pamięci próbowałaby skasować go
    # drugi raz (StaleDataError przy flushu).
    await db.refresh(entity, attribute_names=list(_SCHEDULES))
    orders = await _load_orders(db, contract_id)
    outcome = await sync_contract_from_orders(
        db,
        entity,
        orders,
        actor_id=actor_id,
        today=today,
        auto_activate=auto_activate,
        follow_order_unit=follow_order_unit,
        follow_order_currency=follow_order_currency,
    )
    outcome.order_cost_ids = await sync_orders_cost_from_contract(
        db, entity, orders, today=today
    )
    if audit and outcome.changed:
        db.add(
            Activity(
                entity_type="contract",
                entity_id=contract_id,
                action="synced_with_orders",
                user_id=actor_id,
                details=outcome.as_details(),
            )
        )
    await db.flush()
    if outcome.changed:
        # Zapis wygasił serwerowe ``updated_at`` zamówień i kontraktu, które
        # wołający mógł już odświeżyć i zaraz zserializuje.
        await _refresh_expired(db)
    return outcome


async def _refresh_expired(db: AsyncSession) -> None:
    """Doczytaj atrybuty, które synchronizacja zostawiła wygasłe.

    Dwa źródła: ``updated_at`` z serwerowym ``onupdate`` wygasa po każdym
    UPDATE (także gdy synchronizacja poprawiła koszt zamówienia, które handler
    już ``refresh``-ował), a wycofany savepoint wygasza obiekty zmienione w jego
    obrębie. Handler buduje po commicie odpowiedź z tych samych obiektów,
    a leniwe doczytanie w sesji async to ``MissingGreenlet`` (500 bez CORS).

    Tylko WYGASŁE atrybuty, nigdy cały obiekt: ``refresh`` bez listy wygasza
    relacje ``lazy="select"`` (np. harmonogramy stawek kontraktu), po które
    odpowiedź sięga zaraz potem.
    """
    for obj in list(db.identity_map.values()):
        state = inspect(obj)
        if state.deleted or state.detached:
            continue
        expired = list(state.expired_attributes)
        if not expired:
            continue
        try:
            await db.refresh(obj, attribute_names=expired)
        except Exception:  # noqa: BLE001 — obiekt mógł zniknąć razem z savepointem
            logger.debug("contract-order sync: refresh skipped for %r", obj)


async def sync_enabled(db: AsyncSession) -> bool:
    """Synchronizacja działa dopiero po jednorazowej korekcie przy wdrożeniu.

    Korekta zapisuje migawkę raportu zgodności SPRZED synchronizacji. Gdyby
    blok w ``entrypoint.sh`` padł (loguje i idzie dalej), a zapisy zamówień
    już synchronizowały, migawka z następnego deployu nie pokazałaby
    niezgodności, które zdążyły się „wyrównać". Do markera system zachowuje
    się dokładnie jak przed wdrożeniem.
    """
    return await db.get(AppSetting, REPAIR_MARKER) is not None


async def resync_contract_safely(
    db: AsyncSession,
    contract: Contract | int,
    **kwargs: object,
) -> Optional[ContractSyncOutcome]:
    """``resync_contract`` dla ścieżek, których synchronizacja nie może wywrócić.

    PATCH kontraktu, aneks, przedłużenie, zakończenie, potwierdzenie podpisu:
    błąd synchronizacji (projekcji) nie może cofać zapisu, o który prosił
    użytkownik — ląduje w logu (Sentry), a stan odtworzy najbliższy zapis.
    """
    if not await sync_enabled(db):
        return None
    try:
        async with db.begin_nested():
            return await resync_contract(db, contract, **kwargs)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        contract_id = contract if isinstance(contract, int) else contract.id
        logger.exception("contract-order sync failed for contract %s", contract_id)
        await _refresh_expired(db)
        return None


async def sync_pending_order_contracts(
    db: AsyncSession,
    *,
    actor_id: Optional[int] = None,
    today: Optional[date] = None,
) -> list[ContractSyncOutcome]:
    """Zsynchronizuj kontrakty, których zamówienia zmieniły się w tej sesji.

    Wołane PRZED commitem zapisu zamówienia. Awaria synchronizacji nie
    wywraca zapisu zamówienia (savepoint + log): synchronizacja jest
    projekcją, którą najbliższy zapis albo przebieg dobowy odtworzy, a
    zamówienie jest dokumentem od klienta.
    """
    await db.flush()
    pending: set[int] = db.info.pop(_PENDING_KEY, None) or set()
    pending -= db.info.pop(_SKIP_KEY, None) or set()
    if not pending or not await sync_enabled(db):
        return []
    outcomes: list[ContractSyncOutcome] = []
    try:
        async with db.begin_nested():
            for contract_id in sorted(pending):
                outcome = await resync_contract(
                    db, contract_id, actor_id=actor_id, today=today
                )
                if outcome is not None:
                    outcomes.append(outcome)
    except Exception:  # noqa: BLE001
        # `exception`, nie `warning`: Sentry łapie od ERROR, a cicho padająca
        # synchronizacja to dokładnie ten objaw, od którego wyszło zgłoszenie.
        logger.exception("contract-order sync failed for contracts %s", sorted(pending))
        await _refresh_expired(db)
        outcomes = []
    finally:
        # Własne zapisy synchronizacji (koszt w zamówieniu) dopisały te same
        # kontrakty do listy — nie ma czego robić drugi raz.
        db.info.pop(_PENDING_KEY, None)
    return outcomes


@event.listens_for(Session, "after_flush")
def _collect_order_contracts(session: Session, _flush_context: object) -> None:
    """Zapamiętaj kontrakty, których zamówienia ten flush dodał, zmienił lub usunął.

    Czyta WYŁĄCZNIE stan już obecny w obiekcie (``state.dict`` i
    ``committed_state``) — bez leniwego doczytywania w środku flusha. Stary
    ``contract_id`` z ``committed_state`` łapie przepięcie zamówienia na inny
    kontrakt: tamten też musi oddać okres i stawkę.
    """
    pending: Optional[set[int]] = None
    for obj in chain(session.new, session.dirty, session.deleted):
        if not isinstance(obj, ClientOrder):
            continue
        state = inspect(obj)
        for contract_id in (
            state.dict.get("contract_id"),
            state.committed_state.get("contract_id"),
        ):
            if isinstance(contract_id, int):
                if pending is None:
                    pending = session.info.setdefault(_PENDING_KEY, set())
                pending.add(contract_id)


# ── Przebieg dobowy ──────────────────────────────────────────────────────────


async def run_daily_order_cost_sync(
    db: AsyncSession, *, today: Optional[date] = None, batch_size: int = 200
) -> int:
    """Wprowadź w zamówieniach zaplanowane zmiany stawki kosztowej z kontraktów.

    Harmonogram kontraktu może mieć kilka podwyżek naprzód (120 → 125 od 01.10,
    125 → 130 od 01.12); zamówienie niesie jedną liczbę, więc codzienny
    przebieg ustawia tę obowiązującą danego dnia. Idempotentny — zapis tylko
    przy różnicy. Zwraca liczbę zmienionych zamówień.
    """
    today = today or business_today()
    if await db.get(AppSetting, REPAIR_MARKER) is None:
        logger.info("contract-order cost sync: waiting for one-time repair marker")
        return 0
    contract_ids = list(
        (
            await db.scalars(
                select(ClientOrder.contract_id)
                .join(Contract, Contract.id == ClientOrder.contract_id)
                .where(
                    ClientOrder.status.in_(list(COST_TARGET_ORDER_STATUSES)),
                    ClientOrder.order_group_id.is_(None),
                    ClientOrder.client_id == Contract.client_id,
                    Contract.status != ContractStatus.void,
                )
                .distinct()
                .order_by(ClientOrder.contract_id)
            )
        ).all()
    )
    from app.services.contract_rates import RATE_SCHEDULE_LOADS

    changed_total = 0
    for offset in range(0, len(contract_ids), batch_size):
        batch = contract_ids[offset : offset + batch_size]
        contracts = (
            await db.scalars(
                select(Contract)
                .where(Contract.id.in_(batch))
                .options(*RATE_SCHEDULE_LOADS)
            )
        ).all()
        orders_by_contract: dict[int, list[ClientOrder]] = {}
        for order in (
            await db.scalars(
                select(ClientOrder)
                .where(
                    ClientOrder.contract_id.in_(batch),
                    ClientOrder.order_group_id.is_(None),
                    ClientOrder.status.in_(list(COST_TARGET_ORDER_STATUSES)),
                )
                .order_by(ClientOrder.id)
            )
        ).all():
            orders_by_contract.setdefault(order.contract_id, []).append(order)
        for contract in contracts:
            try:
                # Savepoint per kontrakt: jeden rekord z danymi, których nie da
                # się pogodzić, nie może zatrzymać podwyżek wszystkich innych.
                async with db.begin_nested():
                    changed = await sync_orders_cost_from_contract(
                        db,
                        contract,
                        orders_by_contract.get(contract.id, []),
                        today=today,
                    )
            except Exception:  # noqa: BLE001
                logger.exception(
                    "contract-order cost sync: contract %s skipped", contract.id
                )
                await _refresh_expired(db)
                continue
            if changed:
                changed_total += len(changed)
                db.add(
                    Activity(
                        entity_type="contract",
                        entity_id=contract.id,
                        action="synced_with_orders",
                        user_id=None,
                        details={
                            "order_cost_synced": sorted(changed),
                            "source": "daily_cost_sync",
                            "business_day": today.isoformat(),
                        },
                    )
                )
        await db.flush()
    await _refresh_revenue_caches(db, today=today)
    # Własne zapisy przebiegu nie potrzebują drugiej synchronizacji.
    db.info.pop(_PENDING_KEY, None)
    return changed_total


async def backfill_missing_order_periods(
    db: AsyncSession, *, batch_size: int = 200
) -> int:
    """Uzupełnij okres zamówienia kontraktom, których nikt nie zsynchronizował.

    Synchronizacja odpala się przy ZAPISIE zamówienia, a jednorazowa korekta
    przy wdrożeniu ruszała wyłącznie szkice. Kontrakt aktywny, którego
    zamówienia nikt od tamtej pory nie zapisał, nie miał więc okresu zamówienia,
    choć zamówienie go ma (UAT B-B02: 362 z 386 kontraktów).

    Tylko OKRES (osobne pola ``client_order_*``, bez wpływu na kwoty) i tylko
    tam, gdzie go nie ma — ta sama reguła co krok 5 pełnej synchronizacji
    (najnowsze uzupełnione zamówienie). Stawki przychodowej, jednostki i waluty
    ten przebieg świadomie NIE przepisuje: przestawienie jednostki przelicza
    każdą kwotę kontraktu, a to zmiana pieniędzy, nie projekcja dat —
    domyka ją pełna synchronizacja przy najbliższym zapisie zamówienia.
    Idempotentny: po uzupełnieniu start nie jest pusty, więc drugi przebieg
    kontraktu nie wybiera.
    """
    if not await sync_enabled(db):
        return 0
    contract_ids = list(
        (
            await db.scalars(
                select(ClientOrder.contract_id)
                .join(Contract, Contract.id == ClientOrder.contract_id)
                .where(
                    Contract.status != ContractStatus.void,
                    # Okres wpisany kiedyś ręcznie (sama data końca) zostaje:
                    # przebieg uzupełnia wyłącznie BRAK, nigdy nie nadpisuje.
                    Contract.client_order_start_date.is_(None),
                    Contract.client_order_end_date.is_(None),
                    ClientOrder.client_id == Contract.client_id,
                    ClientOrder.start_date.is_not(None),
                    ClientOrder.status.in_(list(SOURCE_ORDER_STATUSES)),
                    # To samo, co wymaga ``order_revenue_terms`` — bez tego
                    # szkice bez stawki byłyby wczytywane co noc na próżno.
                    or_(ClientOrder.rate_client > 0, ClientOrder.md_rate_revenue > 0),
                )
                .distinct()
                .order_by(ClientOrder.contract_id)
            )
        ).all()
    )
    filled = 0
    for offset in range(0, len(contract_ids), batch_size):
        batch = contract_ids[offset : offset + batch_size]
        contracts = (
            await db.scalars(select(Contract).where(Contract.id.in_(batch)))
        ).all()
        orders_by_contract: dict[int, list[ClientOrder]] = {}
        for order in (
            await db.scalars(
                select(ClientOrder)
                .where(ClientOrder.contract_id.in_(batch))
                .order_by(ClientOrder.id)
            )
        ).all():
            orders_by_contract.setdefault(order.contract_id, []).append(order)
        for contract in contracts:
            if (
                contract.status == ContractStatus.void
                or contract.client_order_start_date is not None
                or contract.client_order_end_date is not None
            ):
                continue
            terms = [
                t
                for order in orders_by_contract.get(contract.id, [])
                if order.client_id == contract.client_id
                and (t := order_revenue_terms(order)) is not None
            ]
            if not terms:
                continue
            latest = _latest(terms)
            previous_end = contract.client_order_end_date
            contract.client_order_start_date = latest.start
            contract.client_order_end_date = latest.end
            filled += 1
            db.add(
                Activity(
                    entity_type="contract",
                    entity_id=contract.id,
                    action="synced_with_orders",
                    user_id=None,
                    details={
                        "source": "daily_period_backfill",
                        "source_order_id": latest.order_id,
                        "period_changed": True,
                        "client_order_start_date": latest.start.isoformat(),
                        "client_order_end_date": (
                            latest.end.isoformat() if latest.end else None
                        ),
                        "previous_client_order_end_date": (
                            previous_end.isoformat() if previous_end else None
                        ),
                    },
                )
            )
        await db.flush()
    return filled


async def _refresh_revenue_caches(db: AsyncSession, *, today: date) -> int:
    """Przestaw cache ``rate_client``/``margin`` kontraktów, którym właśnie wszedł krok.

    Odczyty pieniędzy idą przez harmonogram, ale kolumna jest tym, co widzi
    formularz kontraktu i filtr „marża od" w rejestrze. Kolumna nieodświeżona
    po wejściu przyszłej stawki (130 zł od 01.10) wracałaby z formularza jako
    „zmiana" i dopisywała krok ze starą kwotą. Okno 31 dni łapie przebiegi
    pominięte przez restarty.
    """
    from datetime import timedelta

    from app.services.contract_rates import RATE_SCHEDULE_LOADS

    ids = list(
        (
            await db.scalars(
                select(ContractClientRate.contract_id)
                .where(
                    ContractClientRate.effective_from <= today,
                    ContractClientRate.effective_from > today - timedelta(days=31),
                )
                .distinct()
            )
        ).all()
    )
    refreshed = 0
    for offset in range(0, len(ids), 200):
        for contract in (
            await db.scalars(
                select(Contract)
                .where(
                    Contract.id.in_(ids[offset : offset + 200]),
                    Contract.status != ContractStatus.void,
                )
                .options(*RATE_SCHEDULE_LOADS)
            )
        ).all():
            current = contract.effective_client_rate(today)
            if not _same_amount(contract.rate_client, current):
                contract.rate_client = current
                contract.margin = contract.calculate_margin()
                refreshed += 1
        await db.flush()
    return refreshed
