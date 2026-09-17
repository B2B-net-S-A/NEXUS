"""Ślad rozliczeniowy zamówienia — co blokuje jego usunięcie.

Usunięcie zamówienia (samodzielnego albo linii zamówienia MD/kosztowego)
kasuje wiersz trwale, a razem z nim — kaskadowo — zaraportowane MD
i zaimportowane faktury. Tych danych nie wprowadzono na ekranie zamówienia,
tylko importem z Finansów, więc usunięcie nie może ich zabierać po cichu.
Stąd jedna reguła dla obu tras: zamówienie z rozliczeniami nie jest
kasowane (409), a użytkownik dostaje wskazówkę, co zrobić zamiast tego.
"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.md_consumption import (
    ClientOrderInvoiceConsumption,
    ClientOrderMdConsumption,
)


async def settlement_blockers(db: AsyncSession, order_ids: Sequence[int]) -> list[str]:
    """Opisy rozliczeń przypiętych do zamówień; pusta lista = nic nie blokuje."""

    ids = [order_id for order_id in order_ids if order_id is not None]
    if not ids:
        return []
    blockers: list[str] = []
    md_rows = await db.scalar(
        select(func.count(ClientOrderMdConsumption.id)).where(
            ClientOrderMdConsumption.order_id.in_(ids)
        )
    )
    if md_rows:
        blockers.append(f"rozliczone MD konsultantów ({md_rows})")
    invoice_rows = await db.scalar(
        select(func.count(ClientOrderInvoiceConsumption.id)).where(
            ClientOrderInvoiceConsumption.order_id.in_(ids)
        )
    )
    if invoice_rows:
        blockers.append(f"zaimportowane faktury ({invoice_rows})")
    return blockers


async def assert_order_has_no_settlements(
    db: AsyncSession, order_id: int, *, subject: str, alternative: str
) -> None:
    """409, gdy zamówienie ma rozliczenia — usunięcie skasowałoby je razem z nim.

    ``subject`` mówi, CO nie może zostać usunięte („konsultanta z zamówienia",
    „tego zamówienia"), a ``alternative`` — czym zakończyć współpracę zamiast
    kasowania (inne przyciski na obu ekranach).
    """

    blockers = await settlement_blockers(db, [order_id])
    if not blockers:
        return
    raise HTTPException(
        409,
        detail=(
            f"Nie można usunąć {subject} — są do niego przypięte rozliczenia: "
            + ", ".join(blockers)
            + ". Usunięcie skasowałoby też tę historię. Jeżeli współpraca się "
            f"skończyła — {alternative}. Jeżeli to pomyłka do wycofania, "
            "najpierw usuń rozliczenia."
        ),
    )
