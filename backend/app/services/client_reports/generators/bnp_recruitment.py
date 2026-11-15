"""Raport miesięczny rekrutacji w szablonie BNP (#3265) jako generator katalogu.

Liczenie zostaje w ``services/bnp_report`` i ``api/bnp_report.py`` (reguły
kolumn uzgodnione z Delivery Leadem 09.11.2026). Katalog tylko woła ten sam
odczyt i ten sam skoroszyt, więc przycisk w Projektach i okno pobrania dają
identyczny plik.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.client_reports.registry import (
    Generator,
    ReportContext,
    ReportData,
    SummaryLine,
    register,
)


async def _load(db: AsyncSession, ctx: ReportContext) -> ReportData:
    # Import leniwy: moduł trasy importuje katalog (dostępność przycisku).
    from app.api.bnp_report import _load_report
    from app.services.bnp_report.workbook import build_workbook, report_filename

    month = ctx.period.key
    rows, bands, source = await _load_report(db, ctx.client_id, month)
    cv = sum(row.cv for row in rows)
    offers = sum(row.offers for row in rows)
    attention = sum(1 for row in rows if row.needs_attention)
    checks: list[str] = []
    if source == "none":
        checks.append(
            "Brak widełek stawek z umowy — kolumny zgodności stawki zostaną puste."
        )
    elif source == "contract":
        checks.append(
            "Widełki odczytane z umowy, niezapisane — sprawdź je w Projektach przed wysłaniem."
        )
    if attention:
        checks.append(
            f"{attention} rekrutacji do sprawdzenia (rola albo seniority z nazwy)."
        )
    return ReportData(
        lines=(
            SummaryLine("Rekrutacje otwarte w miesiącu", str(len(rows)), True),
            SummaryLine("CV wysłane", str(cv)),
            SummaryLine("Oferty", str(offers)),
            SummaryLine(
                "Widełki stawek",
                {"saved": "zapisane", "contract": "z umowy", "none": "brak"}[source],
            ),
        ),
        checks=tuple(checks),
        file_bytes=build_workbook(rows),
        file_name=report_filename(month),
    )


register(
    Generator(
        key="bnp_recruitment_monthly",
        label="Raport miesięczny rekrutacji (szablon BNP)",
        description="Dwa arkusze banku: rekrutacje miesiąca, CV, SLA, zgodność stawki, oferty.",
        rhythms=("monthly",),
        loader=_load,
        needs_client_rate=True,
    )
)
