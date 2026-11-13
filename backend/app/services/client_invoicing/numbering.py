"""Numeracja faktur wystawianych w NEXUSIE: seria × miesiąc → kolejny numer (E4).

* ``assign`` — numer nadawany tuż przed wysyłką do KSeF, w transakcji
  wysyłki, pod blokadą wiersza serii (``SELECT … FOR UPDATE``). Dwie
  równoległe wysyłki czekają na siebie, więc nie dostaną tego samego numeru;
  unikalny indeks ``uq_client_issued_invoices_number`` jest drugą zaporą.
* ``release`` — wycofanie faktury z numerem, która nie weszła do obrotu
  (odrzucona przez KSeF, wysyłka nieudana): numer wraca do serii tylko,
  gdy był ostatni wydany. Inaczej faktura zostaje jako ``cancelled`` —
  ślad niewykorzystanego numeru.
* ``set_next`` — „następny numer” z ekranu ustawień (np. kontynuacja numeracji
  z eBI24 w połowie miesiąca). Nie może zejść do numeru już wydanego.

Miesiąc numeracji = miesiąc daty wystawienia (``P_1``).
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_issued_invoice import ClientInvoiceSeries, ClientIssuedInvoice
from app.services.client_invoice_issue_schema import NUMBER_MAX, SERIES


class NumberingError(ValueError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        self.status_code = status_code
        super().__init__(message)


def format_number(pattern: str, number: int, year: int, month: int) -> str:
    return (
        pattern.replace("{n}", str(number))
        .replace("{mm}", f"{month:02d}")
        .replace("{yyyy}", f"{year:04d}")
    )


async def _locked_series(
    db: AsyncSession, code: str, year: int, month: int
) -> ClientInvoiceSeries:
    await db.execute(
        insert(ClientInvoiceSeries)
        .values(series_code=code, period_year=year, period_month=month, next_number=1)
        .on_conflict_do_nothing(
            index_elements=["series_code", "period_year", "period_month"]
        )
    )
    series = await db.scalar(
        select(ClientInvoiceSeries)
        .where(
            ClientInvoiceSeries.series_code == code,
            ClientInvoiceSeries.period_year == year,
            ClientInvoiceSeries.period_month == month,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert series is not None
    return series


async def _highest_issued(db: AsyncSession, code: str, year: int, month: int) -> int:
    value = await db.scalar(
        select(func.max(ClientIssuedInvoice.number_seq)).where(
            ClientIssuedInvoice.series_code == code,
            ClientIssuedInvoice.number_year == year,
            ClientIssuedInvoice.number_month == month,
        )
    )
    return int(value or 0)


async def assign(
    db: AsyncSession, invoice: ClientIssuedInvoice, *, pattern: str
) -> str:
    """Nadaje numer fakturze bez numeru (bez commita; blokada do końca transakcji)."""

    if invoice.number_seq is not None:
        return invoice.invoice_number or ""
    year, month = invoice.issue_date.year, invoice.issue_date.month
    series = await _locked_series(db, invoice.series_code, year, month)
    number = series.next_number
    # Ręcznie wpisany „następny numer” mógł zostać za numerami już wydanymi.
    number = max(
        number, await _highest_issued(db, invoice.series_code, year, month) + 1
    )
    if number > NUMBER_MAX:
        raise NumberingError("Seria wyczerpała numery w tym miesiącu.")
    invoice.number_seq = number
    invoice.number_year = year
    invoice.number_month = month
    invoice.invoice_number = format_number(pattern, number, year, month)
    series.next_number = number + 1
    await db.flush()
    return invoice.invoice_number


async def release(db: AsyncSession, invoice: ClientIssuedInvoice) -> bool:
    """Wycofanie numeru faktury spoza obrotu; ``True`` = numer wrócił do serii."""

    if invoice.number_seq is None:
        return True
    series = await _locked_series(
        db, invoice.series_code, int(invoice.number_year), int(invoice.number_month)
    )
    if series.next_number == invoice.number_seq + 1:
        series.next_number = invoice.number_seq
        await db.flush()
        return True
    return False


async def set_next(
    db: AsyncSession,
    *,
    code: str,
    year: int,
    month: int,
    next_number: int,
    actor_id: int,
) -> ClientInvoiceSeries:
    if code not in SERIES:
        raise NumberingError("Nie ma takiej serii.", 422)
    if not 1 <= next_number <= NUMBER_MAX:
        raise NumberingError("Następny numer musi być od 1 do 999999.", 422)
    series = await _locked_series(db, code, year, month)
    highest = await _highest_issued(db, code, year, month)
    if next_number <= highest:
        raise NumberingError(
            f"W tym miesiącu wydano już numer {highest} — następny musi być większy."
        )
    series.next_number = next_number
    series.updated_by = actor_id
    await db.flush()
    return series


async def series_view(
    db: AsyncSession, *, year: int, month: int, patterns: dict[str, str]
) -> list[dict[str, Any]]:
    rows = {
        row.series_code: row
        for row in await db.scalars(
            select(ClientInvoiceSeries).where(
                ClientInvoiceSeries.period_year == year,
                ClientInvoiceSeries.period_month == month,
            )
        )
    }
    out = []
    for code in SERIES:
        row: Optional[ClientInvoiceSeries] = rows.get(code)
        highest = await _highest_issued(db, code, year, month)
        next_number = max(row.next_number if row else 1, highest + 1)
        out.append(
            {
                "code": code,
                "pattern": patterns[code],
                "next_number": next_number,
                "next_label": format_number(patterns[code], next_number, year, month),
                "highest_issued": highest or None,
            }
        )
    return out


__all__ = [
    "NumberingError",
    "assign",
    "format_number",
    "release",
    "series_view",
    "set_next",
]
