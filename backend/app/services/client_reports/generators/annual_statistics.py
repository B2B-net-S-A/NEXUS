"""Roczna „Statystyka”: wartość zamówień z okresu i czas personelu per profil.

Wartość = suma netto zamówień ze startem w okresie, osobno per waluta (bez
przeliczania kursów). Czas personelu = MD zaraportowane w zużyciu zamówień
klienta za miesiące okresu; profil to rola (tytuł rekrutacji) kontraktu
zamówienia, a bez niej „bez roli”.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_reports.generators.client_data import (
    md_grouped,
    md_in_period,
    order_value,
    orders_in_period,
    sheet_amount,
    sheet_number,
    totals_by_currency,
)
from app.services.client_reports.registry import (
    Generator,
    ReportContext,
    ReportData,
    Sheet,
    SummaryLine,
    format_amount,
    register,
)


def format_md(value: Decimal) -> str:
    text = f"{Decimal(value).quantize(Decimal('0.01')):,}".replace(",", " ").replace(
        ".", ","
    )
    return text.removesuffix(",00")


async def _load(db: AsyncSession, ctx: ReportContext) -> ReportData:
    period = ctx.period
    orders = await orders_in_period(db, ctx.client_id, period.start, period.end)
    totals = totals_by_currency((o.currency, order_value(o)) for o in orders)
    profiles = md_grouped(
        await md_in_period(db, ctx.client_id, period.start, period.end), "role"
    )
    md_total = sum((md for _, md in profiles), Decimal(0))

    lines = [SummaryLine("Zamówienia ze startem w okresie", str(len(orders)), True)]
    lines += [
        SummaryLine(f"Kwota netto ({cur})", format_amount(amount))
        for cur, amount in totals.items()
    ]
    lines.append(SummaryLine("Czas personelu łącznie (MD)", format_md(md_total), True))
    lines += [SummaryLine(f"MD: {profile}", format_md(md)) for profile, md in profiles]

    checks: list[str] = []
    no_value = sum(1 for o in orders if order_value(o) is None)
    if no_value:
        checks.append(
            f"{no_value} zamówień bez wartości w NEXUSIE — kwota łączna jest zaniżona."
        )
    if len(totals) > 1:
        checks.append(
            "Zamówienia w kilku walutach — kwoty podane osobno, bez przeliczenia kursu."
        )
    if not profiles:
        checks.append(
            "Brak zaraportowanych MD za miesiące okresu — sprawdź import zużycia."
        )

    sheets = (
        Sheet(
            "Kwota zamówień",
            ("Waluta", "Kwota netto"),
            tuple((cur, sheet_amount(amount)) for cur, amount in totals.items()),
            widths=(10, 18),
            note="Zamówienia ze startem w okresie; bez anulowanych i szkiców.",
        ),
        Sheet(
            "Czas personelu",
            ("Profil", "MD"),
            (
                *((profile, sheet_number(md)) for profile, md in profiles),
                ("Razem", sheet_number(md_total)),
            ),
            widths=(36, 12),
        ),
    )
    return ReportData(lines=tuple(lines), sheets=sheets, checks=tuple(checks))


GENERATOR = register(
    Generator(
        key="annual_statistics",
        label="Statystyka roczna (kwota zamówień i czas personelu)",
        description="Kwota netto zamówień z okresu per waluta i MD personelu łącznie i per profil.",
        rhythms=("annual", "contract_year"),
        loader=_load,
        needs_amounts=True,
    )
)
