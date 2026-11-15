"""Raport zaangażowania przed spotkaniem zarządczym z klientem.

Arkusze: podsumowanie zespołu, konsultanci, role, faktury sprzedaży per
miesiąc usługi i waluta oraz pusta tabela „KPI i zmiany” — tych danych NEXUS
nie prowadzi. Marży tu nie ma (liczy ją osobny moduł).

Osoba to kandydat z kontraktem u klienta (podpisanym, nie unieważnionym),
który trwał choć jeden dzień okresu. Kolejne kontrakty tej samej osoby
(przedłużenia) składają się w jedno zaangażowanie: początek = najwcześniejszy
start, koniec = najpóźniejszy koniec albo brak, gdy któryś trwa bez końca.
Przerwy między kontraktami nie skracają stażu. Staż w miesiącach liczy się
od początku zaangażowania do jego końca, najdalej do końca okresu.
Koniec w ostatnim dniu okresu = osoba jest jeszcze „na koniec okresu”, więc
osoby na koniec + odeszły = wszyscy w okresie.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_reports.generators.client_data import (
    NO_ROLE,
    InvoiceRow,
    sales_invoices,
    sheet_amount,
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
from app.services.client_reports.schedule import MONTHS_PL, Period

DAYS_PER_MONTH = 30.4375
KPI_NOTE = "NEXUS nie prowadzi KPI ani rejestru zmian — uzupełnij przed wysłaniem."


@dataclass(frozen=True)
class ContractSpan:
    candidate_id: int
    person: str
    start_date: date
    end_date: Optional[date]
    role: Optional[str]
    project: Optional[str]


@dataclass(frozen=True)
class Engagement:
    person: str
    role: Optional[str]
    project: Optional[str]
    start_date: date
    end_date: Optional[date]
    tenure_months: float


_SPANS_SQL = text(
    """
    WITH serving AS (
        SELECT k.id, k.candidate_id, k.start_date, k.end_date, k.job_id, k.project_name
          FROM contracts k
         WHERE k.client_id = :client_id
           AND k.voided_at IS NULL
           AND k.status::text IN ('active', 'ending', 'ended')
           AND k.start_date IS NOT NULL
           AND k.start_date <= :end
    )
    SELECT s.candidate_id, trim(concat_ws(' ', c.name, c.lastname)) AS person,
           s.start_date, s.end_date, j.title, nullif(trim(s.project_name), '')
      FROM serving s
      JOIN candidates c ON c.id = s.candidate_id
      LEFT JOIN jobs j ON j.id = s.job_id
     WHERE s.candidate_id IN (
               SELECT candidate_id FROM serving
                WHERE end_date IS NULL OR end_date >= :start
           )
     ORDER BY person, s.start_date
    """
)


async def _contract_spans(
    db: AsyncSession, client_id: int, period: Period
) -> list[ContractSpan]:
    result = await db.execute(
        _SPANS_SQL, {"client_id": client_id, "start": period.start, "end": period.end}
    )
    return [ContractSpan(*row) for row in result.all()]


def tenure_months(start: date, end: date) -> float:
    return round(max((end - start).days + 1, 0) / DAYS_PER_MONTH, 1)


def engagements(spans: Iterable[ContractSpan], period: Period) -> list[Engagement]:
    """Kontrakty osoby → jedno zaangażowanie; tylko osoby obecne w okresie."""
    by_person: dict[int, list[ContractSpan]] = defaultdict(list)
    for span in spans:
        by_person[span.candidate_id].append(span)
    out: list[Engagement] = []
    for items in by_person.values():
        if not any(s.end_date is None or s.end_date >= period.start for s in items):
            continue
        latest = max(items, key=lambda s: s.start_date)
        start = min(s.start_date for s in items)
        end = (
            None
            if any(s.end_date is None for s in items)
            else max(s.end_date for s in items)
        )
        until = min(end, period.end) if end else period.end
        out.append(
            Engagement(
                latest.person,
                latest.role,
                latest.project,
                start,
                end,
                tenure_months(start, until),
            )
        )
    return sorted(out, key=lambda e: (e.person, e.start_date))


@dataclass(frozen=True)
class TeamSummary:
    at_end: int
    joined: int
    left: int
    avg_tenure: Optional[float]


def team_summary(people: Sequence[Engagement], period: Period) -> TeamSummary:
    at_end = sum(1 for e in people if e.end_date is None or e.end_date >= period.end)
    joined = sum(1 for e in people if e.start_date >= period.start)
    left = sum(1 for e in people if e.end_date is not None and e.end_date < period.end)
    avg = (
        round(sum(e.tenure_months for e in people) / len(people), 1) if people else None
    )
    return TeamSummary(at_end, joined, left, avg)


def roles_count(people: Iterable[Engagement]) -> list[tuple[str, int]]:
    counts = Counter(e.role or NO_ROLE for e in people)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def invoices_by_month(
    invoices: Iterable[InvoiceRow],
) -> list[tuple[date, str, int, Decimal]]:
    """(miesiąc usługi, waluta, liczba faktur, netto) — korekty liczą się kwotą różnicy."""
    groups: dict[tuple[date, str], list[Decimal]] = defaultdict(list)
    for invoice in invoices:
        month = invoice.service_month or invoice.issue_date
        if month is None:
            continue
        groups[(month.replace(day=1), invoice.currency or "—")].append(
            invoice.net_amount
        )
    return [
        (month, currency, len(amounts), sum(amounts, Decimal(0)))
        for (month, currency), amounts in sorted(groups.items())
    ]


def month_label(month: date) -> str:
    return f"{MONTHS_PL[month.month - 1]} {month.year}"


async def _load(db: AsyncSession, ctx: ReportContext) -> ReportData:
    period = ctx.period
    people = engagements(await _contract_spans(db, ctx.client_id, period), period)
    summary = team_summary(people, period)
    invoices = await sales_invoices(
        db, ctx.client_id, period.start, period.end, by_service_month=True
    )
    finance = invoices_by_month(invoices)
    net_totals: dict[str, Decimal] = defaultdict(Decimal)
    for _, currency, _, net in finance:
        net_totals[currency] += net

    avg_text = (
        f"{summary.avg_tenure:.1f}".replace(".", ",")
        if summary.avg_tenure is not None
        else "—"
    )
    lines = [
        SummaryLine("Osoby na koniec okresu", str(summary.at_end), True),
        SummaryLine("weszły w okresie", str(summary.joined)),
        SummaryLine("odeszły w okresie", str(summary.left)),
        SummaryLine("średni staż (mies.)", avg_text),
    ]
    lines += [
        SummaryLine(f"Faktury netto ({currency})", format_amount(amount))
        for currency, amount in sorted(net_totals.items())
    ]
    checks = ["Uzupełnij arkusz „KPI i zmiany” — NEXUS nie ma tych danych."]
    if not people:
        checks.append("Brak konsultantów u klienta w okresie.")
    if not invoices:
        checks.append(
            "Brak faktur sprzedaży za miesiące okresu — sprawdź pobranie z KSeF."
        )

    sheets = (
        Sheet(
            "Podsumowanie",
            (
                "Okres",
                "Osoby na koniec okresu",
                "Weszły",
                "Odeszły",
                "Średni staż (mies.)",
            ),
            (
                (
                    period.label,
                    summary.at_end,
                    summary.joined,
                    summary.left,
                    summary.avg_tenure,
                ),
            ),
            widths=(24, 22, 10, 10, 20),
        ),
        Sheet(
            "Konsultanci",
            ("Osoba", "Rola", "Projekt", "Start", "Koniec", "Staż (mies.)"),
            tuple(
                (e.person, e.role, e.project, e.start_date, e.end_date, e.tenure_months)
                for e in people
            ),
            widths=(28, 28, 28, 12, 12, 12),
        ),
        Sheet(
            "Role", ("Rola", "Liczba osób"), tuple(roles_count(people)), widths=(32, 12)
        ),
        Sheet(
            "Finanse",
            ("Miesiąc usługi", "Waluta", "Liczba faktur", "Netto"),
            tuple(
                (month_label(m), cur, count, sheet_amount(net))
                for m, cur, count, net in finance
            ),
            widths=(20, 8, 14, 16),
            note="Faktury sprzedaży z KSeF według miesiąca usługi; korekty kwotą różnicy.",
        ),
        Sheet(
            "KPI i zmiany",
            ("Obszar", "Wskaźnik / zmiana", "Wartość", "Komentarz"),
            (),
            widths=(24, 36, 14, 40),
            note=KPI_NOTE,
        ),
    )
    return ReportData(lines=tuple(lines), sheets=sheets, checks=tuple(checks))


GENERATOR = register(
    Generator(
        key="engagement_report",
        label="Raport zaangażowania (spotkanie zarządcze)",
        description="Zespół na koniec okresu, wejścia i odejścia, staż, role i faktury per miesiąc — bez marży.",
        rhythms=("quarterly", "semiannual"),
        loader=_load,
        needs_amounts=True,
    )
)
