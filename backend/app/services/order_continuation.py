"""Czy kończące się zamówienie ma już dodaną kontynuację.

Jedna reguła „zamówienie kończy się BEZ KONTYNUACJI w ciągu N dni" (audyt
24.09.2026, S1 — do tego dnia żyła w sześciu kopiach). Czytają ją:

* karta w panelu „Moi klienci" (``rule_periodic_order_ending``),
* dzwonek (``dl_portal_expiry_scanner._scan_orders``),
* kafelek pulpitu „Zamówienia kończące się w 30 dni" (``custom_metrics``),
* pigułka „Bez kontynuacji 30d" na profilu klienta — pole liczone na serwerze
  w odpowiedzi listy kontraktorów (``ending_without_successor_*``).

Lustro ``covers_after`` z ``services/order_facts.py`` (Finanse → „Kończące się
zamówienia"): zamówienie nie wymaga działania, gdy inne zamówienie tego samego
kontraktu trwa (albo dopiero się zacznie) po jego końcu. Szkic się liczy —
niedokończone przyszłe zamówienie to też zaplanowana kontynuacja (ticket
09.2026) — ale NIE porzucony szkic bez daty końca i bez stawki przychodowej
(szkic z podpisu umowy, W2). Anulowane się nie liczy, zamknięte bez daty końca
ani zamknięte z datą w przyszłości też nie (to historia, nie następca).

Zakres kontynuacji jest ten sam, który widzi zakładka:

* zamówienie okresowe (bez grupy) — inne zamówienia okresowe kontraktu; linia
  zamówienia MD/kosztowego tej osoby NIE jest kontynuacją, bo karta
  kontraktora jej nie pokazuje i alert przeczyłby zakładce;
* linia zamówienia MD/kosztowego — inne linie tego kontraktu, z datą końca
  linii albo (gdy pusta) jej grupy.

Które zamówienia w ogóle „kończą się": okresowe (bez grupy) u wszystkich
klientów, a linie zamówień MD/kosztowych WYŁĄCZNIE u klientów z
``EXTENDED_ORDER_ALERT_CLIENT_IDS`` i tylko w zamówieniu aktywnym — u
pozostałych klientów linię kończy wyczerpanie budżetu, nie kalendarz.
Wyjątek: dzwonek 30/14/7 obejmuje u każdego klienta linie BEZ budżetu MD
(kosztowe), bo te skaner wygasania domyka datą (M9, audyt 24.09.2026).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Collection, Optional, Sequence

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import GROUP_STATUS_ACTIVE, ClientOrderGroup

#: Horyzont pigułki „Bez kontynuacji 30d" i kafelka pulpitu.
ENDING_WITHOUT_CONTINUATION_DAYS = 30

#: Statusy zamówienia, które może „kończyć się" (szkic nie jest zamówieniem,
#: zakończone i anulowane już się skończyły).
ENDING_ORDER_STATUSES = (ClientOrderStatus.active, ClientOrderStatus.paused)


def order_has_continuation(*, today: Optional[date] = None) -> ColumnElement[bool]:
    """Skorelowane ``EXISTS`` dla ``ClientOrder`` z zewnętrznego zapytania.

    Wołający filtruje zamówienia z niepustym ``end_date`` — dla nich porównanie
    „trwa po końcu" ma sens.
    """
    today = today or business_today()
    nxt = aliased(ClientOrder)
    nxt_group = aliased(ClientOrderGroup)
    nxt_end = func.coalesce(nxt.end_date, nxt_group.end_date)
    nxt_revenue = func.coalesce(nxt.rate_client, nxt.md_rate_revenue, 0)
    empty_draft = and_(
        nxt.status == ClientOrderStatus.draft,
        nxt_end.is_(None),
        nxt_revenue <= 0,
    )
    covers_after = or_(
        # Aktywna linia MD z budżetem pracuje po dacie końca — lustro
        # ``OrderFact.works_until_md_exhausted``. WYŁĄCZNIE linia zamówienia
        # MD/kosztowego: samodzielne zamówienie okresowe z ``md_total`` (np.
        # Credit Agricole) nie jest rozliczane importem MD, więc jego
        # „pozostałe MD” nie maleją i tłumiłyby alert każdego kolejnego
        # zamówienia kontraktu bez końca (audyt 24.09.2026, M10).
        and_(
            nxt.status == ClientOrderStatus.active,
            nxt.order_group_id.isnot(None),
            nxt.md_total.isnot(None),
            func.coalesce(nxt.md_remaining, 0) > 0,
        ),
        and_(nxt_end.is_(None), nxt.status != ClientOrderStatus.completed),
        and_(
            nxt_end > ClientOrder.end_date,
            or_(nxt.status != ClientOrderStatus.completed, nxt_end <= today),
        ),
    )
    same_family = or_(
        and_(ClientOrder.order_group_id.is_(None), nxt.order_group_id.is_(None)),
        and_(
            ClientOrder.order_group_id.isnot(None),
            nxt.order_group_id.isnot(None),
        ),
    )
    return (
        select(nxt.id)
        .outerjoin(nxt_group, nxt.order_group_id == nxt_group.id)
        .where(
            nxt.contract_id == ClientOrder.contract_id,
            nxt.id != ClientOrder.id,
            nxt.status != ClientOrderStatus.cancelled,
            ~empty_draft,
            same_family,
            covers_after,
        )
        .correlate(ClientOrder)
        .exists()
    )


def order_ending_without_continuation(
    start: date,
    stop: date,
    *,
    extended_client_ids: Collection[int],
    today: Optional[date] = None,
    include_date_closed_lines: bool = False,
) -> ColumnElement[bool]:
    """Zamówienie kończy się w ``[start, stop]`` i nie ma kontynuacji.

    Predykat dla zapytań po ``ClientOrder`` (bez wymaganego złączenia z grupą).
    Pusta lista klientów rozszerzonych daje ``IN ()`` = fałsz, więc linie grup
    odpadają u wszystkich.

    ``include_date_closed_lines`` (dzwonek 30/14/7) dokłada linie zamówień
    MD/kosztowych BEZ budżetu MD u każdego klienta: te linie skaner wygasania
    domyka DATĄ (``_promote_statuses``, ``periodic_due``), więc bez dzwonka
    gasły bez żadnego ostrzeżenia (audyt 24.09.2026, M9). Linię z budżetem MD
    kończy wyczerpanie budżetu, nie kalendarz — ta zostaje poza dzwonkiem
    u klientów spoza listy rozszerzonej.
    """
    active_groups = select(ClientOrderGroup.id).where(
        ClientOrderGroup.status == GROUP_STATUS_ACTIVE
    )
    scopes = [
        ClientOrder.order_group_id.is_(None),
        and_(
            ClientOrder.client_id.in_(sorted(extended_client_ids)),
            ClientOrder.order_group_id.in_(active_groups),
        ),
    ]
    if include_date_closed_lines:
        scopes.append(
            and_(
                ClientOrder.order_group_id.isnot(None),
                ClientOrder.md_total.is_(None),
            )
        )
    return and_(
        ClientOrder.status.in_(ENDING_ORDER_STATUSES),
        or_(*scopes),
        ClientOrder.end_date.isnot(None),
        ClientOrder.end_date >= start,
        ClientOrder.end_date <= stop,
        ~order_has_continuation(today=today),
    )


# ── Lustro w Pythonie (odpowiedź listy kontraktorów) ────────────────────────


@dataclass(frozen=True)
class EndingWithoutSuccessor:
    order_id: int
    end_date: date
    days_left: int


def _revenue(order: ClientOrder) -> Decimal:
    raw = order.rate_client if order.rate_client is not None else order.md_rate_revenue
    return Decimal(str(raw)) if raw is not None else Decimal("0")


def _covers_after(other: ClientOrder, ended_on: date, today: date) -> bool:
    status = ClientOrderStatus(other.status)
    if status == ClientOrderStatus.cancelled:
        return False
    # Lustro gałęzi SQL wyżej: aktywna LINIA MD z budżetem pracuje po dacie
    # końca (``OrderFact.works_until_md_exhausted``). Bez tego pigułka
    # „Bez kontynuacji” liczyła inaczej niż karta DL, dzwonek i Finanse.
    # Samodzielne zamówienie okresowe z ``md_total`` się nie liczy (M10).
    if (
        status == ClientOrderStatus.active
        and other.order_group_id is not None
        and other.md_total is not None
        and (other.md_remaining or 0) > 0
    ):
        return True
    if (
        status == ClientOrderStatus.draft
        and other.end_date is None
        and _revenue(other) <= 0
    ):
        return False
    if other.end_date is None:
        return status != ClientOrderStatus.completed
    if status == ClientOrderStatus.completed and other.end_date > today:
        return False
    return other.end_date > ended_on


def ending_without_successor(
    orders: Sequence[ClientOrder],
    *,
    today: Optional[date] = None,
    days: Optional[int] = ENDING_WITHOUT_CONTINUATION_DAYS,
) -> Optional[EndingWithoutSuccessor]:
    """Zamówienie OKRESOWE kontraktu, które kończy się bez kontynuacji.

    Ta sama reguła co :func:`order_ending_without_continuation`, liczona na
    zamówieniach okresowych jednego kontraktu (już wczytanych). Z kilku zwraca
    to, które kończy się najwcześniej. ``days=None`` = bez górnej granicy
    (filtr „kończy się w ciągu N dni” na profilu klienta: najwcześniejsze
    takie zamówienie odpowiada na pytanie dla KAŻDEGO N).
    """
    today = today or business_today()
    stop = today + timedelta(days=days) if days is not None else None
    periodic = [o for o in orders if o.order_group_id is None]
    found: Optional[ClientOrder] = None
    for order in periodic:
        if ClientOrderStatus(order.status) not in ENDING_ORDER_STATUSES:
            continue
        end = order.end_date
        if end is None or end < today or (stop is not None and end > stop):
            continue
        if any(
            other.id != order.id and _covers_after(other, end, today)
            for other in periodic
        ):
            continue
        if found is None or end < found.end_date:  # type: ignore[operator]
            found = order
    if found is None or found.end_date is None:
        return None
    return EndingWithoutSuccessor(
        order_id=found.id,
        end_date=found.end_date,
        days_left=(found.end_date - today).days,
    )
