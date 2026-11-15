"""Zestawienie zaangażowania: ile osób świadczyło usługi dla klienta w okresie.

Pierwszy klient: BNP (aneks do umowy ramowej, co miesiąc do 5. dnia). Liczba
osób = kontrakty klienta podpisane i nie unieważnione, które choć jednego dnia
okresu trwały. Imiona i nazwiska w pliku tylko z parametrem „Lista osób”, bo
umowa wymaga liczby.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_reports.generators.common import (
    ContractInPeriod,
    contracts_in_period,
)
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


def people_in_period(
    rows: list[ContractInPeriod], start: date, end: date
) -> tuple[int, int, int]:
    """Osoby, nie kontrakty: zmiana stawki w połowie miesiąca to drugi kontrakt
    tej samej osoby. Weszła = jej najwcześniejszy kontrakt zaczyna się
    w okresie; zakończyła = najpóźniejszy kończy się w okresie."""
    by_person: dict[object, list[ContractInPeriod]] = {}
    for row in rows:
        by_person.setdefault(row.candidate_id or ("k", row.contract_id), []).append(row)
    started = ended = 0
    for contracts in by_person.values():
        first = min(c.start_date for c in contracts if c.start_date)
        if first >= start:
            started += 1
        if all(c.end_date is not None for c in contracts):
            last = max(c.end_date for c in contracts if c.end_date)
            if last <= end:
                ended += 1
    return len(by_person), started, ended


async def _load(db: AsyncSession, ctx: ReportContext) -> ReportData:
    period = ctx.period
    rows = await contracts_in_period(db, ctx.client_id, period.start, period.end)
    people, started_count, ended_count = people_in_period(
        rows, period.start, period.end
    )
    by_order = Counter(r.order_number or NO_ORDER for r in rows)
    without_order = by_order.get(NO_ORDER, 0)

    lines = (
        SummaryLine(
            "Członkowie zespołu świadczący usługi w okresie", str(len(rows)), True
        ),
        SummaryLine(
            "kontrakty z numerem zamówienia",
            f"{len(rows) - without_order} z {len(rows)}",
        ),
        SummaryLine("weszli w okresie", str(started_count)),
        SummaryLine("zakończyli w okresie", str(ended_count)),
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
        ((period.label, people, started_count, ended_count),),
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
