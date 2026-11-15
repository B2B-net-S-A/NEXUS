"""Zestawienie zaangażowania: ile osób świadczyło usługi dla klienta w okresie.

Pierwszy klient: BNP (aneks do umowy ramowej, co miesiąc do 5. dnia). Liczba
osób = kontrakty klienta podpisane i nie unieważnione, które choć jednego dnia
okresu trwały. Imiona i nazwiska w pliku tylko z parametrem „Lista osób”, bo
umowa wymaga liczby.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_reports.generators.common import contracts_in_period
from app.services.client_reports.registry import (
    Generator,
    ParamField,
    ReportContext,
    ReportData,
    Sheet,
    SummaryLine,
    param,
    register,
)

NO_ORDER = "(bez numeru zamówienia)"


async def _load(db: AsyncSession, ctx: ReportContext) -> ReportData:
    period = ctx.period
    rows = await contracts_in_period(db, ctx.client_id, period.start, period.end)
    started = [r for r in rows if r.start_date and r.start_date >= period.start]
    ended = [r for r in rows if r.end_date and r.end_date <= period.end]
    by_order = Counter(r.order_number or NO_ORDER for r in rows)
    without_order = by_order.get(NO_ORDER, 0)

    lines = (
        SummaryLine(
            "Członkowie zespołu świadczący usługi w okresie", str(len(rows)), True
        ),
        SummaryLine("z numerem zamówienia", str(len(rows) - without_order)),
        SummaryLine("weszli w okresie", str(len(started))),
        SummaryLine("zakończyli w okresie", str(len(ended))),
    )
    checks: list[str] = []
    if without_order:
        checks.append(
            f"{without_order} os. bez numeru zamówienia w NEXUSIE — uzupełnij zamówienie albo wyślij z uwagą."
        )
    summary = Sheet(
        "Zestawienie",
        (
            "Okres",
            "Liczba członków zespołu",
            "Weszli w okresie",
            "Zakończyli w okresie",
        ),
        ((period.label, len(rows), len(started), len(ended)),),
        widths=(24, 26, 20, 22),
    )
    orders = Sheet(
        "Według zamówień",
        ("Zamówienie", "Liczba osób"),
        tuple(sorted(by_order.items())),
        widths=(30, 14),
    )
    sheets = [summary, orders]
    if param(ctx, GENERATOR, "list_people"):
        sheets.append(
            Sheet(
                "Osoby",
                ("Lp.", "Członek zespołu", "Zamówienie", "Od", "Do"),
                tuple(
                    (
                        index,
                        r.person,
                        r.order_number or NO_ORDER,
                        r.start_date,
                        r.end_date if r.end_date and r.end_date <= period.end else None,
                    )
                    for index, r in enumerate(rows, 1)
                ),
                widths=(6, 32, 24, 12, 12),
            )
        )
    return ReportData(lines=lines, sheets=tuple(sheets), checks=tuple(checks))


GENERATOR = register(
    Generator(
        key="headcount_month",
        label="Zestawienie zaangażowania (liczba osób)",
        description="Ile osób świadczyło usługi w okresie, z podziałem na zamówienia.",
        rhythms=("monthly", "quarterly"),
        loader=_load,
        params=(
            ParamField(
                "list_people",
                "Lista osób w pliku",
                "bool",
                False,
                "Umowa zwykle wymaga liczby; lista imienna tylko na prośbę klienta.",
            ),
        ),
    )
)
