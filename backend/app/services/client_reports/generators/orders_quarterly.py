"""Zestawienie Zleceń: zamówienia klienta z okresu na koniec kwartału.

Klient wymaga co kwartał listy zleceń z datami realizacji, nazwą projektu,
trybem rozliczenia, wartością, ceną jednostkową i konsultantem. Zakres to
zamówienia ze startem w okresie; parametr „Także trwające” dokłada zamówienia
rozpoczęte wcześniej, które w okresie jeszcze trwały.

Tryb: zamówienie kosztowe (``cost``) to „ryczałt” — rozlicza stały budżet
kwotowy grupy; MD, okresowe (godzinowe albo dzienne) i stare zamówienia bez
typu to „T&M”, bo klient płaci za przepracowany czas
(``client_data.order_mode``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_reports.generators.client_data import (
    OrderRow,
    order_label,
    order_mode,
    order_unit_price,
    order_value,
    orders_in_period,
    sheet_amount,
    totals_by_currency,
)
from app.services.client_reports.registry import (
    Generator,
    ParamField,
    ReportContext,
    ReportData,
    Sheet,
    SummaryLine,
    format_amount,
    param,
    register,
)

HEADERS = (
    "Zlecenie",
    "Projekt",
    "Tryb",
    "Od",
    "Do",
    "Wartość netto",
    "Waluta",
    "Cena jednostkowa",
    "Jednostka",
    "Konsultant",
)


def order_sheet_row(order: OrderRow) -> tuple:
    price, unit = order_unit_price(order)
    return (
        order_label(order),
        order.project,
        order_mode(order.order_type),
        order.start_date,
        order.end_date,
        sheet_amount(order_value(order)),
        order.currency,
        sheet_amount(price),
        unit,
        order.person,
    )


def orders_checks(orders: Sequence[OrderRow]) -> list[str]:
    checks: list[str] = []
    no_value = sum(1 for o in orders if order_value(o) is None)
    if no_value:
        checks.append(
            f"{no_value} zleceń bez wartości w NEXUSIE — uzupełnij w pliku przed wysłaniem."
        )
    no_project = sum(1 for o in orders if not o.project)
    if no_project:
        checks.append(f"{no_project} zleceń bez nazwy projektu ani roli.")
    no_person = sum(1 for o in orders if not o.person)
    if no_person:
        checks.append(
            f"{no_person} zleceń bez konsultanta (brak kontraktu przy zamówieniu)."
        )
    return checks


def totals_lines(totals: dict[str, Decimal]) -> tuple[SummaryLine, ...]:
    return tuple(
        SummaryLine(f"Wartość netto ({currency})", format_amount(amount))
        for currency, amount in totals.items()
    )


async def _load(db: AsyncSession, ctx: ReportContext) -> ReportData:
    include_active: Optional[bool] = param(ctx, GENERATOR, "include_active")
    orders = await orders_in_period(
        db,
        ctx.client_id,
        ctx.period.start,
        ctx.period.end,
        include_active=bool(include_active),
    )
    totals = totals_by_currency((o.currency, order_value(o)) for o in orders)
    scope = (
        "ze startem w okresie lub trwające"
        if include_active
        else "ze startem w okresie"
    )
    lines = (
        SummaryLine(f"Zlecenia {scope}", str(len(orders)), True),
        *totals_lines(totals),
    )
    sheet = Sheet(
        "Zestawienie Zleceń",
        HEADERS,
        tuple(order_sheet_row(o) for o in orders),
        widths=(22, 32, 10, 12, 12, 16, 8, 16, 10, 28),
    )
    checks = orders_checks(orders)
    if not orders:
        checks.append(
            "Brak zleceń w okresie — sprawdź zakres albo wyślij informację, że nie było zleceń."
        )
    return ReportData(lines=lines, sheets=(sheet,), checks=tuple(checks))


GENERATOR = register(
    Generator(
        key="orders_quarterly",
        label="Zestawienie Zleceń",
        description="Zlecenia z okresu: daty, projekt, tryb T&M albo ryczałt, wartość, cena jednostkowa, konsultant.",
        rhythms=("quarterly", "annual"),
        loader=_load,
        needs_amounts=True,
        needs_client_rate=True,
        params=(
            ParamField(
                "include_active",
                "Także zlecenia trwające",
                "bool",
                False,
                "Domyślnie tylko zlecenia rozpoczęte w okresie; włącz, gdy klient chce też trwające.",
            ),
        ),
    )
)
