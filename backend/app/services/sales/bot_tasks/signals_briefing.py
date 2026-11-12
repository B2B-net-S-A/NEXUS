"""Rodzaje z 0676: ``signals`` (sygnały → leady) i ``briefing`` (punkty do rozmowy).

Opakowanie istniejącego kodu z ``services/sales/signals.py`` bez zmiany zachowania:
ten sam raport (``RunReport``), ten sam zapis (``signals.ingest``) i ta sama
odpowiedź dla bota. Polecenie mówi to samo co rutyna v1, więc bot z poleceniem v2
robi dla tych rodzajów to, co robił dotąd.

``briefing`` zna też dwa tryby z 0684 (rodzaju biegu ``call_hook`` ani
``meeting_prep`` CHECK bazy nie zna, a migracji tu nie dokładamy):

* ``meeting_prep`` — punkty przed jutrzejszym spotkaniem, zapis jak dotąd do
  ``sales_company_briefings``; ``request.first_meeting`` mówi, z którymi firmami
  to pierwsze spotkanie;
* ``call_hook`` — haczyk przed telefonem (``call_hook.py``): raport ma ``hooks``,
  a punkty dla tych firm odpadają, żeby nie nadpisały punktów firmy.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.sales import SalesSignalRun
from app.services.sales import signals
from app.services.sales.bot_tasks import call_hook
from app.services.sales.bot_tasks.base import BotTask, TaskContext

MEETING_PREP = "meeting_prep"


class BriefingRequest(BaseModel):
    """Pola zlecenia biegu ``briefing``; bieg bez nich zachowuje się jak przed 0684."""

    model_config = ConfigDict(extra="forbid")

    #: Firmy z trybu ``meeting_prep`` (same numery ``ref`` z biegu), z którymi to
    #: pierwsze spotkanie: bot pisze wtedy o firmie ogólnie, a przy pozostałych
    #: o zmianach dotyczących prowadzonej rozmowy. Bez osób i bez treści rozmów.
    first_meeting: Optional[list[int]] = Field(
        default=None, max_length=signals.MAX_FIRMS
    )


class BriefingReport(signals.RunReport):
    """Raport punktów; ``hooks`` tylko dla firm w trybie ``call_hook``."""

    model_config = ConfigDict(extra="forbid")

    hooks: list[call_hook.ReportHook] = Field(
        default_factory=list, max_length=call_hook.MAX_HOOK_FIRMS
    )


def _refs_with(ctx: TaskContext, mode: str) -> list[int]:
    return [int(firm["ref"]) for firm in ctx.firms if firm.get("mode") == mode]


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
    text = (
        "Dla każdej firmy z listy firms przygotuj od 1 do "
        f"{signals.MAX_POINTS} krótkich punktów, do których handlowiec może nawiązać "
        'w rozmowie. mode = "first_call": co się dzieje w firmie ogólnie; '
        'mode = "ongoing": zmiany od ostatnich tygodni, które mogą dotyczyć '
        "prowadzonego tematu. Bierz tylko informacje opublikowane w ostatnich "
        f"{signals.SIGNAL_WINDOW_DAYS} dniach. signals zostaw puste."
    )
    prep = _refs_with(ctx, MEETING_PREP)
    if prep:
        first = [
            ref for ref in prep if ref in set(ctx.request.get("first_meeting") or [])
        ]
        later = [ref for ref in prep if ref not in first]
        text += (
            ' mode = "meeting_prep": jutro albo w najbliższy dzień roboczy handlowiec '
            "ma spotkanie z firmą; punkty mają pomóc mu się przygotować."
        )
        if first:
            text += (
                f" Pierwsze spotkanie z firmą (ref {', '.join(map(str, first))}): "
                "czym firma się zajmuje i co się w niej ostatnio dzieje."
            )
        if later:
            text += (
                f" Kolejne spotkanie, rozmowy już trwają (ref "
                f"{', '.join(map(str, later))}): zmiany z ostatnich tygodni, które "
                "mogą dotyczyć współpracy."
            )
    hooks = _refs_with(ctx, call_hook.CALL_HOOK)
    if hooks:
        text += " " + call_hook.task_text(hooks)
    else:
        text += " hooks zostaw puste."
    return text


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


def _briefing_format() -> dict[str, Any]:
    return {**_report_format(), "hooks": [call_hook.report_format()]}


async def _ingest(
    db: AsyncSession, run: SalesSignalRun, report: Any, now: datetime
) -> dict[str, Any]:
    return await signals.ingest(db, run, report, now=now)


async def _briefing_ingest(
    db: AsyncSession, run: SalesSignalRun, report: BriefingReport, now: datetime
) -> dict[str, Any]:
    """Punkty jak dotąd, poza firmami w trybie ``call_hook``; ich haczyki osobno."""

    hook_refs = call_hook.hook_refs(run)
    points = signals.RunReport.model_validate(
        {
            **report.model_dump(exclude={"hooks", "briefings"}),
            "briefings": [
                briefing.model_dump()
                for briefing in report.briefings
                if briefing.company_ref not in hook_refs
            ],
        }
    )
    summary = await signals.ingest(db, run, points, now=now)
    summary.update(
        await call_hook.save(db, run, report.hooks, today=business_date(now), now=now)
    )
    return summary


def _reply(summary: dict[str, Any]) -> dict[str, Any]:
    """Ta sama odpowiedź co przed rejestrem: liczby leadów, punktów i odrzuceń
    (bieg punktów dokłada liczby haczyków)."""

    dropped = summary["dropped"]
    hooks = {key: summary[key] for key in ("hooks", "hooks_dropped") if key in summary}
    return {
        **hooks,
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
    report_format=_briefing_format,
    report_model=BriefingReport,
    ingest=_briefing_ingest,
    request_model=BriefingRequest,
    lead_feedback=True,
    reply=_reply,
)
