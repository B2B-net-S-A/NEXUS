"""Czy kończące się zamówienie ma już dodaną kontynuację.

Jedna reguła dla alertów o kończących się zamówieniach (karta w panelu „Moi
klienci" i dzwonek). Lustro zakładki „Kończące się 30d" na profilu klienta
(``endingOrderWithoutSuccessor`` w ``frontend/src/lib/client-order-list.ts``)
i ``covers_after`` z ``services/order_facts.py``: zamówienie nie wymaga działania,
gdy inne zamówienie tego samego kontraktu trwa (albo dopiero się zacznie) po
jego końcu. Szkic się liczy — niedokończone przyszłe zamówienie to też
zaplanowana kontynuacja (ticket 09.2026). Anulowane się nie liczy, zamknięte
bez daty końca też nie (to historia, nie następca).

Zakres kontynuacji jest ten sam, który widzi zakładka:

* zamówienie okresowe (bez grupy) — inne zamówienia okresowe kontraktu; linia
  zamówienia MD/kosztowego tej osoby NIE jest kontynuacją, bo karta
  kontraktora jej nie pokazuje i alert przeczyłby zakładce;
* linia zamówienia MD/kosztowego — inne linie tego kontraktu, z datą końca
  linii albo (gdy pusta) jej grupy.
"""

from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup


def order_has_continuation() -> ColumnElement[bool]:
    """Skorelowane ``EXISTS`` dla ``ClientOrder`` z zewnętrznego zapytania.

    Wołający filtruje zamówienia z niepustym ``end_date`` — dla nich porównanie
    „trwa po końcu" ma sens.
    """
    nxt = aliased(ClientOrder)
    nxt_group = aliased(ClientOrderGroup)
    nxt_end = func.coalesce(nxt.end_date, nxt_group.end_date)
    covers_after = or_(
        and_(nxt_end.is_(None), nxt.status != ClientOrderStatus.completed),
        nxt_end > ClientOrder.end_date,
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
            same_family,
            covers_after,
        )
        .correlate(ClientOrder)
        .exists()
    )
