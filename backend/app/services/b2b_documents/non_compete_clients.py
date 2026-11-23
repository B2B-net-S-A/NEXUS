"""Klienci Partnera z ostatnich 12 miesięcy — podpowiedź przy zakazie konkurencji.

Przegląd skrzynki działu umów z 23.11.2026: przy porozumieniu o rozwiązaniu
umowy listę klientów, u których osoba pracowała w ostatnich 12 miesiącach,
dział składał ręcznie. Zakaz konkurencji z umowy B2B trwa 12 miesięcy po jej
rozwiązaniu, więc ta lista mówi, kogo dotyczy decyzja o zwolnieniu.

To tylko zdanie pod polem „Klient, którego dotyczy zwolnienie” (``notes``
w ``GET /documents/prefill``). Pole dalej podpowiada klienta umowy bazowej,
a wybór zostaje przy człowieku: zwolnienie to decyzja handlowa.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.services.client_identity import client_display_name

__all__ = ["RecentClient", "months_back", "recent_clients", "recent_clients_note"]

WINDOW_MONTHS = 12

# Szkic i umowa do podpisu nie oznaczają pracy u klienta, unieważniony kontrakt
# to pomyłka we wpisie.
_NOT_WORKED = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
    ContractStatus.void,
)


@dataclass(frozen=True)
class RecentClient:
    name: str
    # Ostatni dzień kontraktu u tego klienta (koniec projektu); ``None`` przy
    # trwającej współpracy albo zakończeniu bez zapisanej daty.
    last_day: Optional[date]
    ongoing: bool

    def label(self) -> str:
        if self.ongoing:
            return f"{self.name} (trwa)"
        if self.last_day is not None:
            return f"{self.name} (do {self.last_day:%d.%m.%Y})"
        return f"{self.name} (zakończony)"

    def rank(self) -> tuple[int, int]:
        return (1 if self.ongoing else 0, (self.last_day or date.min).toordinal())


def months_back(day: date, months: int) -> date:
    """Ten sam dzień ``months`` miesięcy wcześniej (31.03 → 28/29.02)."""
    total = day.year * 12 + day.month - 1 - months
    year, month = divmod(total, 12)
    month += 1
    for candidate in (day.day, 30, 29, 28):
        try:
            return date(year, month, candidate)
        except ValueError:
            continue
    raise ValueError(day)


async def recent_clients(
    db: AsyncSession, candidate_id: int, *, until: date
) -> list[RecentClient]:
    """Klienci kontraktów tej osoby, które trwały w ciągu 12 miesięcy do ``until``."""
    since = months_back(until, WINDOW_MONTHS)
    project_end = func.coalesce(Contract.end_date, Contract.terminated_at)
    rows = (
        await db.execute(
            select(Client, Contract.status, project_end)
            .join(Client, Client.id == Contract.client_id)
            .where(
                Contract.candidate_id == candidate_id,
                Contract.status.not_in(_NOT_WORKED),
                Contract.start_date.is_not(None),
                Contract.start_date <= until,
                or_(project_end.is_(None), project_end >= since),
            )
        )
    ).all()
    by_client: dict[int, RecentClient] = {}
    for client, status, end in rows:
        item = RecentClient(
            name=(client.legal_name or "").strip() or client_display_name(client),
            last_day=end,
            ongoing=status != ContractStatus.ended and end is None,
        )
        known = by_client.get(client.id)
        if known is None or item.rank() > known.rank():
            by_client[client.id] = item
    return sorted(
        by_client.values(), key=lambda c: (-c.rank()[0], -c.rank()[1], c.name)
    )


def recent_clients_note(clients: list[RecentClient], *, until: date) -> Optional[str]:
    if not clients:
        return None
    since = months_back(until, WINDOW_MONTHS)
    parts = [c.label() for c in clients]
    return (
        f"Klienci tej osoby z kontraktów od {since:%d.%m.%Y}: "
        + ", ".join(parts)
        + ". Zakaz konkurencji trwa 12 miesięcy po rozwiązaniu umowy i dotyczy "
        "klienta z Załącznika nr 3."
    )
