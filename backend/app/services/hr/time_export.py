"""Eksport godzin do CSV (luka z Compassa, 18.10.2026).

Compass miał „Eksport CSV” godzin osoby za zakres miesięcy (Kadry, przełożony,
osoba — ``exportEmployeeTimesheetsCSV``) dla księgowości. Tu to samo, plus
cały zespół za miesiąc dla Płac i Kadr (obok paczki PDF):

* wiersz na wpis: osoba, e-mail, rok, miesiąc, status raportu, data, godziny,
  projekt, opis, źródło wpisu, nadgodziny i ich uzasadnienie,
* separator ``;``, liczby z przecinkiem (polski Excel), UTF-8 z BOM, ``\\r\\n``,
* bez stawek i kwot — moduł czasu ich nie zna,
* tekst od ludzi przez ``export_safety.safe_row`` (wstrzyknięcie formuły),
* zakres najwyżej 24 miesiące (jak Compass).

D6: auto-wpis płatnej puli zdradza rodzaj nieobecności (płatna przerwa, nie
L4) — czytający bez prawa do rodzaju (zastępca przełożonego) widzi „wpis
automatyczny”.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from decimal import Decimal
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.export_safety import safe_row
from app.models.hr_time import Timesheet, TimesheetEntry
from app.models.user import User
from app.services.hr.time_entries import TimeError, validate_period
from app.services.hr.time_pdf import name_slug

MAX_MONTHS = 24

COLUMNS = (
    "Osoba",
    "E-mail",
    "Rok",
    "Miesiąc",
    "Status",
    "Data",
    "Godziny",
    "Projekt",
    "Opis",
    "Źródło",
    # Plik idzie do osób na każdej formie — słowa neutralne, bez „nadgodzin”
    # (decyzja Artura 21.10.2026; bramka uprawnienia bez zmian).
    "Ponad 8 h dziennie",
    "Czego dotyczyły godziny ponad 8 h",
)

STATUS_LABELS = {
    "draft": "szkic",
    "submitted": "wysłany",
    "approved": "zaakceptowany",
}

SOURCE_LABELS = {
    "manual": "wpis",
    "template": "wypełnienie miesiąca",
    "leave_paid": "płatny dzień z puli",
    "compass_import": "import z Compassa",
}
HIDDEN_LEAVE_SOURCE = "wpis automatyczny"


@dataclass(frozen=True)
class Period:
    year: int
    month: int

    @property
    def key(self) -> int:
        return self.year * 12 + self.month - 1

    def label(self) -> str:
        return f"{self.year}-{self.month:02d}"


def parse_period(raw: str) -> Period:
    """``RRRR-MM`` → okres; zły zapis albo miesiąc poza 2020–2100 = 422."""

    text = (raw or "").strip()
    parts = text.split("-")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise TimeError("Miesiąc podaje się jako RRRR-MM.")
    period = Period(int(parts[0]), int(parts[1]))
    validate_period(period.year, period.month)
    return period


def parse_range(start: str, end: str) -> tuple[Period, Period]:
    first, last = parse_period(start), parse_period(end)
    if first.key > last.key:
        raise TimeError("Miesiąc „od” musi być przed miesiącem „do” albo nim samym.")
    if last.key - first.key + 1 > MAX_MONTHS:
        raise TimeError(f"Eksport obejmuje najwyżej {MAX_MONTHS} miesiące.")
    return first, last


def _in_range(first: Period, last: Period):
    return and_(
        or_(
            Timesheet.year > first.year,
            and_(Timesheet.year == first.year, Timesheet.month >= first.month),
        ),
        or_(
            Timesheet.year < last.year,
            and_(Timesheet.year == last.year, Timesheet.month <= last.month),
        ),
    )


def _hours(value: Decimal) -> str:
    return f"{Decimal(value):.2f}".replace(".", ",")


def _source(entry: TimesheetEntry, *, show_leave_source: bool) -> str:
    if entry.source == "leave_paid" and not show_leave_source:
        return HIDDEN_LEAVE_SOURCE
    return SOURCE_LABELS.get(entry.source, entry.source)


def _render(
    rows: list[tuple[TimesheetEntry, Timesheet, User]],
    *,
    show_leave_source: bool,
) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for entry, timesheet, user in rows:
        writer.writerow(
            safe_row(
                [
                    user.name,
                    user.email,
                    str(timesheet.year),
                    f"{timesheet.month:02d}",
                    STATUS_LABELS.get(timesheet.status, timesheet.status),
                    entry.work_date.isoformat(),
                    _hours(entry.hours),
                    entry.project or "",
                    entry.description,
                    _source(entry, show_leave_source=show_leave_source),
                    "tak" if entry.is_overtime else "",
                    entry.overtime_reason or "",
                ]
            )
        )
    return ("﻿" + buffer.getvalue()).encode("utf-8")


def _query():
    return (
        select(TimesheetEntry, Timesheet, User)
        .join(Timesheet, Timesheet.id == TimesheetEntry.timesheet_id)
        .join(User, User.id == Timesheet.user_id)
    )


@dataclass(frozen=True)
class CsvFile:
    content: bytes
    filename: str
    rows: int


async def person_csv(
    db: AsyncSession,
    *,
    user: User,
    first: Period,
    last: Period,
    show_leave_source: bool = True,
) -> CsvFile:
    """Godziny jednej osoby za zakres miesięcy (każdy status raportu)."""

    rows = list(
        (
            await db.execute(
                _query()
                .where(Timesheet.user_id == user.id, _in_range(first, last))
                .order_by(
                    Timesheet.year,
                    Timesheet.month,
                    TimesheetEntry.work_date,
                    TimesheetEntry.id,
                )
            )
        ).all()
    )
    span = first.label() if first == last else f"{first.label()}_{last.label()}"
    return CsvFile(
        content=_render(
            [tuple(row) for row in rows], show_leave_source=show_leave_source
        ),
        filename=f"godziny-{name_slug(user.name)}-{span}.csv",
        rows=len(rows),
    )


async def month_csv(db: AsyncSession, *, year: int, month: int) -> CsvFile:
    """Godziny całego zespołu za miesiąc (Płace, Kadry, admin), każdy status."""

    validate_period(year, month)
    rows = list(
        (
            await db.execute(
                _query()
                .where(Timesheet.year == year, Timesheet.month == month)
                .order_by(
                    User.name, User.id, TimesheetEntry.work_date, TimesheetEntry.id
                )
            )
        ).all()
    )
    return CsvFile(
        content=_render([tuple(row) for row in rows], show_leave_source=True),
        filename=f"godziny-{year}-{month:02d}.csv",
        rows=len(rows),
    )


__all__ = [
    "COLUMNS",
    "CsvFile",
    "MAX_MONTHS",
    "Period",
    "month_csv",
    "parse_period",
    "parse_range",
    "person_csv",
]
