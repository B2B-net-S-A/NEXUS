"""Most do urlopów — JEDYNE miejsce, w którym „Mój miesiąc” czyta nieobecności.

Urlopy żyją w module „leave” (``leave_requests`` + ``leave_request_days``,
dzień per wiersz, ``active`` = wniosek oczekuje albo jest zatwierdzony).
Timesheet nie trzyma kopii urlopu (w Compassie obecność i urlop były dwoma
źródłami prawdy), tylko pyta tędy. Surowy SQL na kolumnach z kontraktu
modułu urlopów: ``leave_request_days(leave_request_id, user_id, day,
fraction, paid, active)`` i ``leave_requests(status, leave_type)``.

Testy podmieniają ``leave_days`` (``monkeypatch``), więc reszta modułu
woła ją przez atrybut modułu, nie przez ``from … import leave_days``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.hr.employment_terms import REPORT_FORMS, reports_absence
from app.services.hr.leave_policy import POOL_TYPES, pool_applies

#: Rodzaje z puli wypoczynkowej — tylko one dają kontraktorowi płatne godziny.
#: Te same zbiory co w urlopach i słowach formy (nazwy zostają dla Płac).
POOL_LEAVE_TYPES: frozenset[str] = POOL_TYPES
CONTRACTOR_TYPES: frozenset[str] = REPORT_FORMS


@dataclass(frozen=True)
class LeaveDay:
    user_id: int
    day: date
    fraction: Decimal
    paid: bool
    status: str  # pending | approved
    leave_type: str
    leave_request_id: str

    @property
    def is_full(self) -> bool:
        return self.fraction >= Decimal("1")

    def is_paid_work_for(self, employment_type: str | None) -> bool:
        """Dzień płatnej puli B2B = auto-wpis godzin.

        Decyzja Compassa z 29.05.2026: kontraktor z pulą rozlicza dzień puli
        jak dzień pracy (od 28.10.2026 „Realizacja usług zgodnie z umową”),
        etat (UoP) i dni bezpłatne blokują timesheet. Wniosek oczekujący
        blokuje zawsze. Na zleceniu puli
        nie ma (D6, ``pool_applies``): dzień z flagą ``paid`` z czasu innej
        formy blokuje dzień jak bezpłatny — bez auto-wpisu 8 h.
        """

        return (
            self.status == "approved"
            and self.paid
            and self.leave_type in POOL_LEAVE_TYPES
            and reports_absence(employment_type)
            and pool_applies(employment_type)
        )


_LEAVE_DAYS_SQL = text(
    """
    SELECT d.user_id, d.day, d.fraction, d.paid, r.status, r.leave_type,
           d.leave_request_id::text AS leave_request_id
      FROM leave_request_days d
      JOIN leave_requests r ON r.id = d.leave_request_id
     WHERE d.active
       AND r.status IN ('pending', 'approved')
       AND d.user_id = ANY(:user_ids)
       AND d.day BETWEEN :start AND :end
     ORDER BY d.user_id, d.day
    """
)


async def leave_days(
    db: AsyncSession, user_ids: Sequence[int], start: date, end: date
) -> list[LeaveDay]:
    """Aktywne dni nieobecności osób w zakresie (włącznie z oboma końcami)."""

    ids = sorted({int(user_id) for user_id in user_ids})
    if not ids:
        return []
    rows = (
        await db.execute(_LEAVE_DAYS_SQL, {"user_ids": ids, "start": start, "end": end})
    ).all()
    return [
        LeaveDay(
            user_id=row.user_id,
            day=row.day,
            fraction=Decimal(str(row.fraction)),
            paid=bool(row.paid),
            status=row.status,
            leave_type=row.leave_type,
            leave_request_id=row.leave_request_id,
        )
        for row in rows
    ]
