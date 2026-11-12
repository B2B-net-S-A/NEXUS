"""Rodzaje z 0676: ``signals`` (sygnały → leady) i ``briefing`` (punkty do rozmowy).

Opakowanie istniejącego kodu z ``services/sales/signals.py`` bez zmiany zachowania:
ten sam raport (``RunReport``), ten sam zapis (``signals.ingest``) i ta sama
odpowiedź dla bota. Polecenie mówi to samo co rutyna v1, więc bot z poleceniem v2
robi dla tych rodzajów to, co robił dotąd.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesSignalRun
from app.services.sales import signals
from app.services.sales.bot_tasks.base import BotTask, TaskContext


def _signals_text(run: SalesSignalRun, ctx: TaskContext) -> str:
    return (
        "Dla każdej firmy z listy firms szukaj sygnałów, że firma może potrzebować "
        "specjalistów IT z zewnątrz (zatrudnianie, restrukturyzacja, nowy program, "
        "kontrakt, inwestycja, zmiana zarządu). Bierz tylko informacje opublikowane "
        f"w ostatnich {signals.SIGNAL_WINDOW_DAYS} dniach. Pomiń adresy z seen_urls "
        "i tematy podobne do rejected. Typ sygnału tylko z signal_types. Siła: strong "
        "tylko gdy źródło wprost mówi o potrzebie ludzi do projektu IT, medium gdy to "
        "rozsądny wniosek, weak gdy to tylko temat do wzmianki. Najwyżej "
        f"{signals.MAX_SIGNALS} sygnałów. Firmy bez sygnału wpisz do no_signal, "
        "briefings zostaw puste."
    )


def _briefing_text(run: SalesSignalRun, ctx: TaskContext) -> str:
    return (
        "Dla każdej firmy z listy firms przygotuj od 1 do "
        f"{signals.MAX_POINTS} krótkich punktów, do których handlowiec może nawiązać "
        'w rozmowie. mode = "first_call": co się dzieje w firmie ogólnie; '
        'mode = "ongoing": zmiany od ostatnich tygodni, które mogą dotyczyć '
        "prowadzonego tematu. "
        'Gdy przy mode = "ongoing" nie ma nic nowego, nie dopisuj punktów na siłę: '
        "wpisz firmę do no_signal. "
        "Bierz tylko informacje opublikowane w ostatnich "
        f"{signals.SIGNAL_WINDOW_DAYS} dniach. signals zostaw puste."
    )


def _report_format() -> dict[str, Any]:
    return {
        "checked_firms": "<liczba sprawdzonych firm>",
        "signals": [
            {
                "company_ref": "<ref z firms>",
                "type": "|".join(signals.SIGNAL_TYPES),
                "title": "...",
                "summary": "...",
                "why_now": "...",
                "url": "https://...",
                "published": "RRRR-MM-DD",
                "strength": "strong|medium|weak",
            }
        ],
        "briefings": [
            {
                "company_ref": "<ref z firms>",
                "points": [
                    {"text": "...", "url": "https://...", "published": "RRRR-MM-DD"}
                ],
            }
        ],
        "no_signal": ["<ref firmy bez sygnału>"],
    }


async def _ingest(
    db: AsyncSession, run: SalesSignalRun, report: Any, now: datetime
) -> dict[str, Any]:
    return await signals.ingest(db, run, report, now=now)


def _reply(summary: dict[str, Any]) -> dict[str, Any]:
    """Ta sama odpowiedź co przed rejestrem: liczby leadów, punktów i odrzuceń."""

    dropped = summary["dropped"]
    return {
        "leads": summary["leads"],
        "leads_new": summary["leads_new"],
        "briefings": summary["briefings"],
        "dropped": {
            "outside_window": len(dropped["outside_window"]),
            "nexus_clients": len(dropped["nexus_clients"]),
            "unknown_company": dropped["unknown_company"],
            "duplicates": dropped["duplicates"],
        },
    }


SIGNALS = BotTask(
    kind="signals",
    task_text=_signals_text,
    report_format=_report_format,
    report_model=signals.RunReport,
    ingest=_ingest,
    lead_feedback=True,
    reply=_reply,
)

BRIEFING = BotTask(
    kind="briefing",
    task_text=_briefing_text,
    report_format=_report_format,
    report_model=signals.RunReport,
    ingest=_ingest,
    lead_feedback=True,
    reply=_reply,
)
