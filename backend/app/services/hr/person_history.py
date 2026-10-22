"""Kartoteka → „Nieobecności i godziny” (przebudowa „Ludzi”, 22.10.2026).

Nieobecności osoby w roku i jej raporty godzin z ostatnich miesięcy — to, co
wcześniej było tylko w „Akceptacjach → Historia wniosków” (bramka
akceptujących) i w „Moim miesiącu” (tylko o sobie). Trasa
``GET /api/hr/people/{id}/history`` pyta tu tylko w pełnym zakresie kartoteki
(osoba, jej przełożony, Kadry, Finanse, admin — ``people.viewer_scope``).

* **D6** — rodzaj nieobecności widzą osoba, przełożony, Kadry i admin
  (``leave_policy.can_see_type``). Reszta pełnego zakresu (Finanse spoza
  kręgu) dostaje „Nieobecność” i tylko zatwierdzone — oczekujące i odrzucone
  widzi krąg D6 (jak podgląd wniosku, decyzja Artura 19.10.2026).
* **Słowa formy** — rodzaj z puli wypoczynkowej na B2B/zleceniu to
  „Przerwa w świadczeniu usług” / „Nieobecność” (``type_label``). Gdy
  patrzący nie widzi formy (Kadry bez Płac), rodzaj z puli to „Nieobecność”,
  bo „Urlop wypoczynkowy” albo „Przerwa…” zdradzałyby formę.
* Anulowane wnioski nie są nieobecnością — nie wracają.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import LeaveRequest
from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import Timesheet, TimesheetEntry
from app.services.hr.leave_policy import POOL_TYPES, type_label
from app.services.hr.leave_queries import request_splits
from app.services.hr.time_month import month_norm_hours

#: Ile miesięcy raportów godzin pokazuje kartoteka (bieżący i pięć wcześniej).
TIMESHEET_MONTHS = 6

NEUTRAL_LABEL = "Nieobecność"

AbsenceState = Literal["planned", "waiting", "used", "rejected"]


def absence_label(
    leave_type: Optional[str],
    employment_type: Optional[str],
    *,
    type_visible: bool,
    form_visible: bool,
) -> str:
    """Etykieta nieobecności dla patrzącego (D6 i słowa formy)."""

    if not type_visible:
        return NEUTRAL_LABEL
    if not form_visible and leave_type in POOL_TYPES:
        return NEUTRAL_LABEL
    return type_label(leave_type, employment_type if form_visible else None)


def absence_state(status: str, start: date, today: date) -> Optional[AbsenceState]:
    """Stan na liście: zaplanowana / czeka / wykorzystana / odrzucona.

    Zatwierdzona, która już się zaczęła, jest „wykorzystana” (dzień trwający
    dziś już się liczy — jak ``leave_balance.day_split``). Anulowana = ``None``.
    """

    if status == "pending":
        return "waiting"
    if status == "rejected":
        return "rejected"
    if status == "approved":
        return "planned" if start > today else "used"
    return None


def recent_months(today: date, count: int = TIMESHEET_MONTHS) -> list[tuple[int, int]]:
    """Bieżący miesiąc i ``count - 1`` wcześniejszych, od najnowszego."""

    year, month = today.year, today.month
    out: list[tuple[int, int]] = []
    for _ in range(count):
        out.append((year, month))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


def employed_in(profile: EmployeeProfile, year: int, month: int) -> bool:
    """Czy miesiąc wypada w zatrudnieniu z kartoteki (start — ostatni dzień)."""

    first = date(year, month, 1)
    last = date(year + month // 12, month % 12 + 1, 1)
    if profile.work_start_date and profile.work_start_date >= last:
        return False
    if profile.last_working_day and profile.last_working_day < first:
        return False
    return True


@dataclass(frozen=True)
class Viewer:
    """Co patrzący widzi w historii osoby."""

    type_visible: bool
    form_visible: bool


async def absences(
    db: AsyncSession,
    profile: EmployeeProfile,
    *,
    year: int,
    today: date,
    viewer: Viewer,
) -> list[dict[str, Any]]:
    """Nieobecności osoby nachodzące na rok, od najnowszej."""

    statuses = (
        ("approved", "pending", "rejected") if viewer.type_visible else ("approved",)
    )
    rows = list(
        await db.scalars(
            select(LeaveRequest)
            .where(
                LeaveRequest.user_id == profile.user_id,
                LeaveRequest.status.in_(statuses),
                LeaveRequest.start_date <= date(year, 12, 31),
                LeaveRequest.end_date >= date(year, 1, 1),
            )
            .order_by(LeaveRequest.start_date.desc(), LeaveRequest.created_at.desc())
        )
    )
    splits = await request_splits(db, rows)
    items: list[dict[str, Any]] = []
    for row in rows:
        state = absence_state(row.status, row.start_date, today)
        if state is None:
            continue
        items.append(
            {
                "id": str(row.id),
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat(),
                "half_day": row.half_day,
                "days_total": f"{splits[row.id].total:.1f}",
                "status": row.status,
                "state": state,
                "leave_type": row.leave_type if viewer.type_visible else None,
                "label": absence_label(
                    row.leave_type,
                    profile.employment_type,
                    type_visible=viewer.type_visible,
                    form_visible=viewer.form_visible,
                ),
            }
        )
    return items


async def timesheets(
    db: AsyncSession, profile: EmployeeProfile, *, today: date
) -> list[dict[str, Any]]:
    """Raporty godzin z ostatnich ``TIMESHEET_MONTHS`` miesięcy, od najnowszego.

    Miesiąc w zatrudnieniu bez raportu to wiersz ``status: null`` (tylko gdy
    osoba składa raport godzin); miesiąc poza zatrudnieniem — bez wiersza.
    Norma to kalendarz firmy × 8 h (ta sama co „Mój miesiąc” i Akceptacje).
    """

    months = recent_months(today)
    period = or_(*(and_(Timesheet.year == y, Timesheet.month == m) for y, m in months))
    rows = (
        await db.execute(
            select(
                Timesheet.id,
                Timesheet.year,
                Timesheet.month,
                Timesheet.status,
                Timesheet.pdf_hash,
                func.coalesce(func.sum(TimesheetEntry.hours), 0),
            )
            .outerjoin(TimesheetEntry, TimesheetEntry.timesheet_id == Timesheet.id)
            .where(Timesheet.user_id == profile.user_id, period)
            .group_by(Timesheet.id)
        )
    ).all()
    found = {
        (year, month): (ts_id, status, pdf_hash, total)
        for ts_id, year, month, status, pdf_hash, total in rows
    }
    items: list[dict[str, Any]] = []
    for year, month in months:
        hit = found.get((year, month))
        if hit is None and not (
            profile.timesheet_required and employed_in(profile, year, month)
        ):
            continue
        ts_id, status, pdf_hash, total = hit if hit else (None, None, None, 0)
        items.append(
            {
                "year": year,
                "month": month,
                "timesheet_id": ts_id,
                "status": status,
                "hours": float(total),
                "norm_hours": await month_norm_hours(db, year, month),
                # PDF jest po akceptacji (``_pdf_response``) i przy zapisanej sumie.
                "has_pdf": status == "approved" and bool(pdf_hash),
            }
        )
    return items
