"""Bieżące zamówienie i znaczniki „Wymaga uwagi” konsultanta u klienta.

Zakładka „Konsultanci” w profilu klienta (decyzja Artura 18.11.2026, wariant B
makiety): osoba z umową i bieżącym zamówieniem w jednym wierszu. Reguły nie są
nowe — to te same, które liczą pigułkę „Bez kontynuacji 30 dni” w Zamówieniach
i dzwonek Delivery Leada (:func:`order_continuation.ending_without_successor`)
oraz flagę „bez projektu” dla COMPASS (:func:`lacks_current_order`, lustro
frontowego ``isCurrentOrder`` z ``lib/client-order-list.ts``). Trzeciej
definicji „bez zamówienia” nie dokładamy.

Wymaga wczytanych ``Contract.client_orders`` i ``ClientOrder.order_group`` —
w sesji async lazy-load to ``MissingGreenlet`` (500 bez nagłówków CORS).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.services.order_continuation import ending_without_successor
from app.services.order_excel_export import is_current_order_period

# Zamówienie zakończone albo anulowane nie „obowiązuje dziś" niezależnie od dat.
# SZKIC celowo LICZY SIĘ jako pokrycie: to zaślepka zakładana hookiem
# zatrudnienia, więc osoba ze szkicem jest obsadzona, tylko zamówienie nie jest
# uzupełnione.
DEAD_ORDER_STATUSES = (ClientOrderStatus.completed, ClientOrderStatus.cancelled)

ATTENTION_NOTICE = "notice"
ATTENTION_NO_CURRENT_ORDER = "no_current_order"
ATTENTION_ORDER_ENDING = "order_ending"


def order_period(order: ClientOrder) -> tuple[Optional[date], Optional[date]]:
    """Okres linii; linia MD/kosztowa bez własnych dat dziedziczy okres grupy."""
    group = order.order_group if order.order_group_id is not None else None
    start = order.start_date or (group.start_date if group else None)
    end = order.end_date or (group.end_date if group else None)
    return start, end


def lacks_current_order(contract: Contract, today: date) -> bool:
    """Czy żywa umowa nie ma dziś żadnego obowiązującego zamówienia.

    Runda 9 (R9-N9-8): linia zamówienia MD/kosztowego zwykle nie niesie
    własnych dat — okres ma grupa (lustro ``order_excel_export``). Bez tego
    konsultant z linią bez dat wychodził „bez projektu” nawet przy zamówieniu
    zakończonym rok temu albo zaczynającym się za pół roku.
    """
    for order in contract.client_orders or ():
        if order.status in DEAD_ORDER_STATUSES:
            continue
        start, end = order_period(order)
        if is_current_order_period(start, end, today):
            return False
    return True


@dataclass(frozen=True)
class ConsultantOrderState:
    """Kolumna „Bieżące zamówienie” i znaczniki wiersza konsultanta."""

    order_start_date: Optional[date]
    order_end_date: Optional[date]
    # Status pokazanego zamówienia — „szkic” liczy się jako pokrycie (zaślepka
    # z hooka zatrudnienia), ale wiersz ma mówić, że zamówienie jest do
    # uzupełnienia.
    order_status: Optional[str]
    # Koniec zamówienia okresowego bez kontynuacji w oknie 30 dni.
    order_ending_on: Optional[date]
    attention: tuple[str, ...]


def _shown_order(contract: Contract, today: date) -> Optional[ClientOrder]:
    """Zamówienie obowiązujące dziś; bez niego — najnowsze nieanulowane.

    Najnowsze (także zakończone) zostaje w kolumnie, żeby było widać, od kiedy
    osoba pracuje bez zamówienia, zamiast pustej komórki.
    """
    orders = [
        order
        for order in contract.client_orders or ()
        if order.status != ClientOrderStatus.cancelled
    ]
    current = [
        order
        for order in orders
        if order.status not in DEAD_ORDER_STATUSES
        and is_current_order_period(*order_period(order), today)
    ]
    pool = current or orders
    if not pool:
        return None
    return max(pool, key=lambda order: order_period(order)[0] or date.min)


def consultant_order_state(
    contract: Contract, today: date, *, is_current: bool
) -> ConsultantOrderState:
    """Stan zamówienia i znaczniki dla wiersza zakładki „Konsultanci”.

    ``is_current`` — umowa już obowiązuje (ta sama reguła co „Obecni”
    w profilu). Planowanej umowy nie oznaczamy brakiem zamówienia: zamówienie
    przychodzi zwykle tuż przed startem.
    """
    shown = _shown_order(contract, today)
    start, end = order_period(shown) if shown is not None else (None, None)
    attention: list[str] = []
    live = contract.status in (ContractStatus.active, ContractStatus.ending)
    if contract.status == ContractStatus.ending:
        attention.append(ATTENTION_NOTICE)
    if live and is_current and lacks_current_order(contract, today):
        attention.append(ATTENTION_NO_CURRENT_ORDER)
    ending = (
        ending_without_successor(contract.client_orders or (), today=today)
        if live
        else None
    )
    if ending is not None:
        attention.append(ATTENTION_ORDER_ENDING)
    return ConsultantOrderState(
        order_start_date=start,
        order_end_date=end,
        order_status=(
            getattr(shown.status, "value", shown.status) if shown is not None else None
        ),
        order_ending_on=ending.end_date if ending is not None else None,
        attention=tuple(attention),
    )
