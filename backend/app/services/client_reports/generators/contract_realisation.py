"""Roczny raport realizacji umowy: zamówienia, wynagrodzenie, specjaliści.

Zamówienia to te ze startem w okresie, wynagrodzenie to faktury sprzedaży
z KSeF wystawione w okresie (z korektami), specjaliści to osoby z MD
zaraportowanymi za miesiące okresu. Terminów realizacji z umowy ani kar
NEXUS nie zna — arkusz „Terminy i kary” zostaje do uzupełnienia.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_reports.generators.client_data import (
    NO_ROLE,
    MdRow,
    invoice_type_label,
    order_label,
    md_in_period,
    order_value,
    orders_in_period,
    sales_invoices,
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

TERMS_NOTE = "NEXUS nie zna terminów realizacji z umowy ani kar — uzupełnij."


def specialists(rows: list[MdRow]) -> list[tuple[str, str, Decimal]]:
    """(osoba, rola, MD) — osoba z kilkoma rolami ma osobny wiersz na każdą."""
    sums: dict[tuple[str, str], Decimal] = {}
    for row in rows:
        key = (row.person or "(bez osoby)", row.role or NO_ROLE)
        sums[key] = sums.get(key, Decimal(0)) + row.md
    return [(person, role, md) for (person, role), md in sorted(sums.items()) if md]


async def _load(db: AsyncSession, ctx: ReportContext) -> ReportData:
    period = ctx.period
    orders = await orders_in_period(db, ctx.client_id, period.start, period.end)
    invoices = await sales_invoices(db, ctx.client_id, period.start, period.end)
    people = specialists(
        await md_in_period(db, ctx.client_id, period.start, period.end)
    )
    order_totals = totals_by_currency((o.currency, order_value(o)) for o in orders)
    paid_totals = totals_by_currency((i.currency, i.net_amount) for i in invoices)

    lines = [SummaryLine("Zamówienia ze startem w okresie", str(len(orders)), True)]
    lines += [
        SummaryLine(f"Wartość zamówień ({c})", format_amount(v))
        for c, v in order_totals.items()
    ]
    lines.append(SummaryLine("Faktury sprzedaży w okresie", str(len(invoices)), True))
    lines += [
        SummaryLine(f"Wynagrodzenie netto ({c})", format_amount(v))
        for c, v in paid_totals.items()
    ]
    lines.append(
        SummaryLine("Specjaliści z MD w okresie", str(len({p for p, _, _ in people})))
    )

    checks = ["Uzupełnij arkusz „Terminy i kary” — NEXUS nie ma tych danych."]
    no_value = sum(1 for o in orders if order_value(o) is None)
    if no_value:
        checks.append(f"{no_value} zamówień bez wartości w NEXUSIE.")
    if not invoices:
        checks.append(
            "Brak faktur sprzedaży wystawionych w okresie — sprawdź pobranie z KSeF."
        )

    sheets = (
        Sheet(
            "Zamówienia",
            (
                "Numer",
                "Tytuł / opis",
                "Od",
                "Do",
                "Wartość netto",
                "Waluta",
                "Konsultant",
            ),
            tuple(
                (
                    order_label(o),
                    " — ".join(part for part in (o.title, o.description) if part)
                    or None,
                    o.start_date,
                    o.end_date,
                    sheet_amount(order_value(o)),
                    o.currency,
                    o.person,
                )
                for o in orders
            ),
            widths=(22, 44, 12, 12, 16, 8, 28),
        ),
        Sheet(
            "Wynagrodzenie",
            ("Numer faktury", "Data wystawienia", "Netto", "Waluta", "Rodzaj"),
            tuple(
                (
                    i.invoice_number,
                    i.issue_date,
                    sheet_amount(i.net_amount),
                    i.currency,
                    invoice_type_label(i),
                )
                for i in invoices
            ),
            widths=(24, 16, 16, 8, 12),
            note="Faktury sprzedaży z KSeF wystawione w okresie; korekta niesie kwotę różnicy.",
        ),
        Sheet(
            "Specjaliści",
            ("Osoba", "Rola", "MD w okresie"),
            tuple((p, r, sheet_number(md)) for p, r, md in people),
            widths=(28, 32, 14),
        ),
        Sheet(
            "Terminy i kary",
            (
                "Zobowiązanie",
                "Termin z umowy",
                "Termin wykonania",
                "Kara umowna",
                "Komentarz",
            ),
            (),
            widths=(32, 16, 16, 14, 40),
            note=TERMS_NOTE,
        ),
    )
    return ReportData(lines=tuple(lines), sheets=sheets, checks=tuple(checks))


GENERATOR = register(
    Generator(
        key="contract_realisation_annual",
        label="Raport realizacji umowy (roczny)",
        description="Zamówienia, wynagrodzenie z faktur, specjaliści z MD i tabela terminów do uzupełnienia.",
        rhythms=("annual",),
        loader=_load,
        needs_amounts=True,
    )
)
