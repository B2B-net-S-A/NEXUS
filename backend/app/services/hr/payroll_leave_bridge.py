"""Most Płac do urlopów (moduł ``leave``): liczba dni nieobecności w miesiącu.

Eksport dla księgowości dostaje WYŁĄCZNIE dwie liczby — dni z puli urlopowej
(``paid``) i pozostałe dni nieobecności — bez rodzaju nieobecności (rodzaj
bywa daną o zdrowiu; D6). Liczą się dni zatwierdzonych wniosków.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class LeaveDays:
    paid: Decimal
    other: Decimal


async def leave_days(db: AsyncSession, start: date, end: date) -> dict[int, LeaveDays]:
    """Dni zatwierdzonych nieobecności z zakresu ``start``–``end`` per osoba."""

    rows = await db.execute(
        text(
            "SELECT d.user_id, "
            "COALESCE(SUM(d.fraction) FILTER (WHERE d.paid), 0) AS paid, "
            "COALESCE(SUM(d.fraction) FILTER (WHERE NOT d.paid), 0) AS other "
            "FROM leave_request_days d "
            "JOIN leave_requests r ON r.id = d.leave_request_id "
            "WHERE d.active AND r.status = 'approved' "
            "AND d.day BETWEEN :start AND :end "
            "GROUP BY d.user_id"
        ),
        {"start": start, "end": end},
    )
    return {
        int(row.user_id): LeaveDays(paid=Decimal(row.paid), other=Decimal(row.other))
        for row in rows
    }


__all__ = ["LeaveDays", "leave_days"]
