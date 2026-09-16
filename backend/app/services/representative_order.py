"""Zamówienie reprezentujące kontrakt „na dziś" — jedna reguła dla profilu i przypisań.

Wyniesione z ``app/api/clients.py`` (ticket #3), bo od 09.2026 czyta ją także
przypisanie umowy wykonawczej Centrum e-Zdrowia. Kopia w drugim miejscu
rozjechałaby tag na profilu z tym, co ustawia ekran przeglądu.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract


def representative_order(
    contract: Contract, on: Optional[date] = None
) -> Optional[ClientOrder]:
    """``None`` gdy kontrakt nie ma ANI JEDNEGO nieanulowanego zamówienia.

    1 kontrakt = N zamówień/przedłużeń, a wiersz konsultanta jest per-KONTRAKT.
    Reguła lustrzana do FE ``splitOrders.activeOrder``: najnowsze ROZPOCZĘTE
    zamówienie (start_date ≤ dziś, nullowe traktowane jak rozpoczęte), a gdy
    wszystkie dopiero przyszłe — najbliższe nadchodzące. Anulowane pomijamy.
    Dzięki temu zaplanowane przedłużenie nie przejmuje wiersza przed startem.
    Wymaga załadowanej relacji ``contract.client_orders`` (selectinload).
    """
    orders = [
        o
        for o in (contract.client_orders or [])
        if o.status != ClientOrderStatus.cancelled
    ]
    if not orders:
        return None
    today = on or business_today()
    started = [o for o in orders if o.start_date is None or o.start_date <= today]
    if started:
        return max(started, key=lambda o: (o.start_date or date.min, o.id))
    return min(orders, key=lambda o: (o.start_date or date.max, o.id))
