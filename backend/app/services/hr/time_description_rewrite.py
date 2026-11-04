"""„Praca standardowa” → słowo formy w szkicach jednego miesiąca (28.10.2026).

Od 28.10.2026 domyślny opis dnia na B2B i zleceniu to „Realizacja usług
zgodnie z umową” (``time_entries.standard_description``). Artur zdecydował
przepisać tylko szkice bieżącego miesiąca: wysłane i przyjęte raporty mają
``pdf_hash`` liczony też z opisu, więc ich treść zostaje. UoP zostaje
z „Praca standardowa”.

Warunki (szkic, bez ``pdf_hash``, bez blokady płac, forma z kartoteki B2B
albo zlecenie, opis dokładnie „Praca standardowa”) są w samym ``UPDATE`` —
raport wysłany między podglądem a zapisem nie zostanie ruszony. ``updated_at``
timesheetu i wpisu = teraz, żeby ponowny import z Compassa uznał zmianę za
zrobioną w NEXUSIE i jej nie cofnął.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import Timesheet, TimesheetEntry
from app.services.hr.employment_terms import REPORT_FORMS
from app.services.hr.time_entries import standard_description

OLD_DESCRIPTION = "Praca standardowa"


@dataclass(frozen=True)
class Rewrite:
    form: str
    timesheets: int
    entries: int


def _scope(year: int, month: int, form: str):
    return and_(
        Timesheet.year == year,
        Timesheet.month == month,
        Timesheet.status == "draft",
        Timesheet.pdf_hash.is_(None),
        Timesheet.payroll_locked.is_(False),
        EmployeeProfile.user_id == Timesheet.user_id,
        EmployeeProfile.employment_type == form,
    )


async def plan(db: AsyncSession, *, year: int, month: int) -> list[Rewrite]:
    """Ile szkiców i wpisów zmieni się per forma (bez zapisu)."""

    out: list[Rewrite] = []
    for form in sorted(REPORT_FORMS):
        row = (
            await db.execute(
                select(
                    func.count(func.distinct(Timesheet.id)),
                    func.count(TimesheetEntry.id),
                )
                .select_from(TimesheetEntry)
                .join(Timesheet, Timesheet.id == TimesheetEntry.timesheet_id)
                .join(EmployeeProfile, EmployeeProfile.user_id == Timesheet.user_id)
                .where(
                    _scope(year, month, form),
                    TimesheetEntry.description == OLD_DESCRIPTION,
                )
            )
        ).one()
        out.append(Rewrite(form=form, timesheets=row[0], entries=row[1]))
    return out


async def apply(db: AsyncSession, *, year: int, month: int) -> list[Rewrite]:
    """Przepisuje opisy; zwraca to, co faktycznie zmieniono."""

    out: list[Rewrite] = []
    for form in sorted(REPORT_FORMS):
        in_scope = select(Timesheet.id).where(_scope(year, month, form))
        touched = (
            (
                await db.execute(
                    update(TimesheetEntry)
                    .where(
                        TimesheetEntry.timesheet_id.in_(in_scope),
                        TimesheetEntry.description == OLD_DESCRIPTION,
                    )
                    .values(
                        description=standard_description(form),
                        updated_at=func.now(),
                    )
                    .returning(TimesheetEntry.timesheet_id)
                    .execution_options(synchronize_session=False)
                )
            )
            .scalars()
            .all()
        )
        sheets = set(touched)
        if sheets:
            await db.execute(
                update(Timesheet)
                .where(Timesheet.id.in_(sheets))
                .values(updated_at=func.now())
                .execution_options(synchronize_session=False)
            )
        out.append(Rewrite(form=form, timesheets=len(sheets), entries=len(touched)))
    return out
