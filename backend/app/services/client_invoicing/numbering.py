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
* Numer wydany poza NEXUSEM też jest wydany (``_highest_outside``): dopóki
  eBI24 działa równolegle, faktury z jego numerami tej serii są w KSeF
  (``client_sales_invoices``). Bez tego pierwsza faktura z NEXUSA dostałaby
  1/11/2026 obok 323 faktur eBI24 z listopada, KSeF odpowiedziałby 440
  („Duplikat faktury”), a ``ksef_send._resolve_duplicate`` przypiąłby do niej
  numer KSeF cudzej faktury (test na KSeF testowym MF 28.11.2026).

Miesiąc numeracji = miesiąc daty wystawienia (``P_1``).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_issued_invoice import ClientInvoiceSeries, ClientIssuedInvoice
from app.models.client_sales_invoice import ClientSalesInvoice
from app.services.client_invoice_issue_schema import NUMBER_MAX, SERIES


class NumberingError(ValueError):
    def __init__(self, message: str, status_code: int = 409) -> None:
        self.status_code = status_code
        super().__init__(message)


def format_number(pattern: str, number: int, year: int, month: int) -> str:
    return (
        pattern.replace("{n}", str(number))
        .replace("{mm}", f"{month:02d}")
        # {m} — miesiąc bez zera, jak w numerach eBI24 („286/9/2026/Benefit”).
        .replace("{m}", str(month))
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


def number_regex(pattern: str, year: int, month: int) -> str:
    """Wyrażenie numeru serii w danym miesiącu; ``{n}`` to grupa z numerem."""

    out = re.escape(pattern)
    for token, value in (
        (re.escape("{n}"), "([0-9]+)"),
        (re.escape("{mm}"), f"{month:02d}"),
        (re.escape("{m}"), str(month)),
        (re.escape("{yyyy}"), f"{year:04d}"),
    ):
        out = out.replace(token, value)
    return f"^{out}$"


async def _highest_outside(
    db: AsyncSession, pattern: Optional[str], year: int, month: int
) -> int:
    """Najwyższy numer serii z faktur sprzedaży w KSeF (eBI24 i NEXUS)."""

    if not pattern or "{n}" not in pattern:
        return 0
    regex = number_regex(pattern, year, month)
    compiled = re.compile(regex)
    best = 0
    for number in await db.scalars(
        select(ClientSalesInvoice.invoice_number).where(
            ClientSalesInvoice.invoice_number.op("~")(regex)
        )
    ):
        found = compiled.match(number or "")
        if found:
            best = max(best, int(found.group(1)))
    return best


async def _highest(
    db: AsyncSession, code: str, year: int, month: int, pattern: Optional[str]
) -> int:
    return max(
        await _highest_issued(db, code, year, month),
        await _highest_outside(db, pattern, year, month),
    )


async def assign(
    db: AsyncSession, invoice: ClientIssuedInvoice, *, pattern: str
) -> str:
    """Nadaje numer fakturze bez numeru (bez commita; blokada do końca transakcji)."""

    if invoice.number_seq is not None:
        return invoice.invoice_number or ""
    year, month = invoice.issue_date.year, invoice.issue_date.month
    series = await _locked_series(db, invoice.series_code, year, month)
    number = series.next_number
    # Ręcznie wpisany „następny numer” mógł zostać za numerami już wydanymi,
    # także w eBI24 (numery tej serii w KSeF).
    number = max(
        number, await _highest(db, invoice.series_code, year, month, pattern) + 1
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
    pattern: Optional[str] = None,
) -> ClientInvoiceSeries:
    if code not in SERIES:
        raise NumberingError("Nie ma takiej serii.", 422)
    if not 1 <= next_number <= NUMBER_MAX:
        raise NumberingError("Następny numer musi być od 1 do 999999.", 422)
    series = await _locked_series(db, code, year, month)
    highest = await _highest(db, code, year, month, pattern)
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
        highest = await _highest(db, code, year, month, patterns.get(code))
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
    "number_regex",
    "release",
    "series_view",
    "set_next",
]
