"""Eksport miesiąca płac do księgowości (XLSX).

Arkusz „Płace” — wiersz na osobę i walutę: godziny zatwierdzone, stawka,
kwota za godziny, premie, razem, dni nieobecności (z puli urlopowej
i pozostałe — liczby, BEZ rodzaju nieobecności), status timesheetu.
Arkusz „Sumy” — sumy per waluta i stan miesiąca (zamknięty albo wstępny).

Wzorzec eksportu NEXUSA: płaskie wiersze zebrane w sesji, budowa skoroszytu
w ``asyncio.to_thread`` (write-only openpyxl), każdy tekst przez
``safe_cell`` (formuły z danych nie wykonują się w arkuszu).
"""

from __future__ import annotations

import asyncio
import io
from decimal import Decimal
from typing import Any

from app.core.export_safety import safe_row
from app.services.hr.payroll_periods import label
from app.services.hr.payroll_report import MonthReport

EMPLOYMENT_LABELS: dict[str, str] = {"uop": "UoP", "b2b": "B2B", "zlecenie": "Zlecenie"}
TIMESHEET_LABELS: dict[str, str] = {
    "draft": "szkic",
    "submitted": "czeka na akceptację",
    "approved": "zaakceptowany",
}

COLUMNS: tuple[str, ...] = (
    "Osoba",
    "Forma",
    "Waluta",
    "Godziny zaakceptowane",
    "W tym nadgodziny",
    "Stawka za godzinę",
    "Za godziny",
    "Premie",
    "Razem",
    "Dni nieobecności z puli urlopowej",
    "Dni nieobecności pozostałe",
    "Timesheet",
)


def _number(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def export_rows(report: MonthReport) -> list[list[Any]]:
    rows: list[list[Any]] = []
    for person in report.people:
        lines = person.lines or ()
        rate_line = next((line for line in lines if line.hourly_rate is not None), None)
        carrier = rate_line or (lines[0] if lines else None)
        timesheet = TIMESHEET_LABELS.get(person.timesheet_status or "", "brak")
        employment = EMPLOYMENT_LABELS.get(person.employment_type or "", "")
        if not lines:
            rows.append(
                safe_row(
                    [
                        person.name,
                        employment,
                        "",
                        _number(person.hours),
                        _number(person.overtime_hours),
                        None,
                        None,
                        0.0,
                        0.0,
                        _number(person.paid_leave_days),
                        _number(person.other_leave_days),
                        timesheet,
                    ]
                )
            )
            continue
        for line in lines:
            carries = line is carrier
            rows.append(
                safe_row(
                    [
                        person.name,
                        employment,
                        line.currency,
                        _number(person.hours) if carries else 0.0,
                        _number(person.overtime_hours) if carries else 0.0,
                        _number(line.hourly_rate),
                        _number(line.hours_amount),
                        _number(line.bonus_total),
                        _number(line.total),
                        _number(person.paid_leave_days) if carries else 0.0,
                        _number(person.other_leave_days) if carries else 0.0,
                        timesheet,
                    ]
                )
            )
    return rows


def summary_rows(report: MonthReport) -> list[list[Any]]:
    state = "zamknięty" if report.status == "closed" else "otwarty — dane wstępne"
    rows: list[list[Any]] = [
        ["Miesiąc", label(report.year, report.month)],
        ["Stan", state],
        ["Osoby", len(report.people)],
        [],
        ["Waluta", "Razem"],
    ]
    for currency, total in report.totals().items():
        rows.append([currency, float(total)])
    return rows


def build_xlsx(rows: list[list[Any]], summary: list[list[Any]]) -> bytes:
    """CPU-bound — wołać przez ``asyncio.to_thread``."""

    from openpyxl import Workbook

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet(title="Płace")
    sheet.append(list(COLUMNS))
    for row in rows:
        sheet.append(row)
    totals = workbook.create_sheet(title="Sumy")
    for row in summary:
        totals.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def render(report: MonthReport) -> bytes:
    return await asyncio.to_thread(
        build_xlsx, export_rows(report), summary_rows(report)
    )


def filename(year: int, month: int) -> str:
    return f"place-{year}-{month:02d}.xlsx"


__all__ = ["COLUMNS", "build_xlsx", "export_rows", "filename", "render", "summary_rows"]
