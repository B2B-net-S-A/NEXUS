"""Rodzaj ``winback`` („Warto wrócić”, G-E): co się zmieniło w firmach po przegranej.

Raz w miesiącu bot dostaje firmy z ``signal_targets.winback_deals`` (przegrana
z powodem „wróć później”, bez otwartej szansy, poza klientami NEXUSA) i szuka
zmian, które dają powód, żeby wrócić. Do bota idą tylko nazwy i domeny firm:
powód przegranej, tytuł szansy i opiekun zostają w NEXUSIE (``request`` pusty).

Raport ma kształt sygnałów (``ReportSignal``, te same limity i okno 120 dni),
a wynik to lead w skrzynce (źródło ``research``, odcisk firma + link jak przy
sygnałach) z ``payload.origin = "winback"`` i danymi przegranej. Lead dostaje
opiekuna firmy, a gdy ten nie pracuje w Sprzedaży, opiekuna przegranej szansy;
bez żadnego z nich lead czeka na „Przejmij i zaplanuj”. Żadnej automatyzacji
kontaktu: powrót planuje człowiek zwykłym zadaniem.

Reguły: ``docs/claude/sprzedaz/sygnaly-grok-bot.md`` („Warto wrócić”).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.sales import SalesCompany, SalesLead, SalesSignalRun
from app.models.user import User
from app.services.effective_access import resolve_effective_access
from app.services.sales import client_gate, signals
from app.services.sales import signal_targets as targets
from app.services.sales.bot_tasks.base import BotTask, TaskContext
from app.services.sales.offers import works_in_sales
from app.services.sales.signals import MAX_FIRMS, MAX_SIGNALS, ReportSignal

logger = logging.getLogger(__name__)

ORIGIN = "winback"


class WinbackReport(BaseModel):
    """Sygnały zmian w firmach z listy; bez punktów do rozmowy."""

    model_config = ConfigDict(extra="forbid")

    # Pole ``signals`` przesłania w ciele klasy moduł o tej samej nazwie,
    # dlatego stałe i model sygnału są importowane wprost.
    checked_firms: int = Field(ge=0, le=MAX_FIRMS)
    signals: list[ReportSignal] = Field(default_factory=list, max_length=MAX_SIGNALS)
    no_signal: list[int] = Field(default_factory=list, max_length=MAX_FIRMS)


def _task_text(run: SalesSignalRun, ctx: TaskContext) -> str:
    return (
        "Firmy z listy firms to nasze dawne tematy sprzedażowe, które się nie "
        "udały. Dla każdej sprawdź, co się w firmie zmieniło i daje powód, żeby "
        "wrócić z ofertą specjalistów IT z zewnątrz: nowy program albo projekt IT, "
        "inwestycja, zatrudnianie, restrukturyzacja, kontrakt, zmiana zarządu. "
        "Bierz tylko informacje opublikowane w ostatnich "
        f"{signals.SIGNAL_WINDOW_DAYS} dniach. Pomiń adresy z seen_urls i tematy "
        "podobne do rejected. Typ tylko z signal_types. W why_now napisz jednym "
        "zdaniem, dlaczego ta zmiana to dobry moment na powrót. Siła: strong tylko "
        "gdy źródło wprost mówi o potrzebie ludzi do projektu IT, medium gdy to "
        "rozsądny wniosek, weak gdy to tylko temat do wzmianki. Najwyżej "
        f"{signals.MAX_SIGNALS} sygnałów. Firmy bez zmian wpisz do no_signal."
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
        "no_signal": ["<ref firmy bez zmian>"],
    }


# ── Plan przyjęcia (bez bazy) ────────────────────────────────────────────


@dataclass
class WinbackPlan:
    leads: list[dict[str, Any]] = field(default_factory=list)
    outside_window: int = 0
    nexus_clients: int = 0
    #: Firma od startu biegu ma otwartą szansę albo przestała się kwalifikować.
    not_eligible: int = 0
    unknown_company: int = 0
    duplicates: int = 0


def pick_assignee(
    company_owner_id: Optional[int],
    deal_owner_id: Optional[int],
    in_sales: set[int],
) -> Optional[int]:
    """Opiekun firmy, potem opiekun przegranej; tylko osoba, która pracuje w Sprzedaży."""

    for candidate in (company_owner_id, deal_owner_id):
        if candidate is not None and candidate in in_sales:
            return candidate
    return None


def plan_intake(
    run: SalesSignalRun,
    report: WinbackReport,
    companies: dict[int, signals.CompanyInfo],
    deals: dict[int, targets.LostDeal],
    clients: dict[int, client_gate.ClientMatch],
    in_sales: set[int],
    *,
    today: date,
) -> WinbackPlan:
    allowed = {int(ref) for ref in run.company_ids}
    plan = WinbackPlan()
    seen: set[str] = set()
    oldest = today - timedelta(days=signals.SIGNAL_WINDOW_DAYS)
    for signal in report.signals:
        company = companies.get(signal.company_ref)
        if signal.company_ref not in allowed or company is None:
            plan.unknown_company += 1
            continue
        if signal.published < oldest or signal.published > today + timedelta(days=1):
            plan.outside_window += 1
            continue
        if company.id in clients:
            plan.nexus_clients += 1
            continue
        deal = deals.get(company.id)
        if deal is None:
            plan.not_eligible += 1
            continue
        key = signals.fingerprint(company.id, signal.url)
        if key in seen:
            plan.duplicates += 1
            continue
        seen.add(key)
        plan.leads.append(
            {
                "source": signals.LEAD_SOURCE,
                "title": signal.title,
                "summary": signal.summary or None,
                "company_name": company.name,
                "company_id": company.id,
                "url": signal.url,
                "score": signals.STRENGTH_SCORE[signal.strength],
                "signal_at": datetime.combine(
                    signal.published, time(12), tzinfo=timezone.utc
                ),
                "fingerprint": key,
                "assignee_user_id": pick_assignee(
                    company.owner_user_id, deal.owner_user_id, in_sales
                ),
                "payload": {
                    "origin": ORIGIN,
                    "run_id": run.id,
                    "type": signal.type,
                    "strength": signal.strength,
                    "why_now": signal.why_now,
                    "published": signal.published.isoformat(),
                    "domain": signals._domain(signal.url),
                    "lost_opportunity_id": deal.opportunity_id,
                    "lost_opportunity_title": deal.title,
                    "lost_reason": deal.lost_reason,
                    "lost_at": deal.lost_at.isoformat(),
                },
            }
        )
    return plan


# ── Zapis ────────────────────────────────────────────────────────────────


async def _in_sales(db: AsyncSession, user_ids: set[int]) -> set[int]:
    if not user_ids:
        return set()
    users = list(
        (await db.scalars(select(User).where(User.id.in_(sorted(user_ids))))).all()
    )
    await resolve_effective_access(db, users)
    return {user.id for user in users if works_in_sales(user)}


async def _ingest(
    db: AsyncSession, run: SalesSignalRun, report: WinbackReport, now: datetime
) -> dict[str, Any]:
    refs = {s.company_ref for s in report.signals} | set(report.no_signal)
    allowed = {int(ref) for ref in run.company_ids}
    rows = {
        company.id: company
        for company in (
            await db.execute(
                select(SalesCompany).where(
                    SalesCompany.id.in_(sorted(refs & allowed)),
                    SalesCompany.archived_at.is_(None),
                )
            )
        ).scalars()
    }
    signal_ids = sorted({s.company_ref for s in report.signals} & set(rows))
    deals = await targets.winback_deals(db, now=now, company_ids=signal_ids)
    clients = await client_gate.match_companies(
        db,
        [
            client_gate.CompanyIdentity(
                company_id=cid,
                client_id=rows[cid].client_id,
                normalized_name=rows[cid].normalized_name,
            )
            for cid in signal_ids
        ],
    )
    owners = {rows[cid].owner_user_id for cid in signal_ids} | {
        deal.owner_user_id for deal in deals.values()
    }
    in_sales = await _in_sales(db, {uid for uid in owners if uid is not None})
    companies = {
        cid: signals.CompanyInfo(id=cid, name=c.name, owner_user_id=c.owner_user_id)
        for cid, c in rows.items()
    }
    plan = plan_intake(
        run,
        report,
        companies,
        deals,
        clients,
        in_sales,
        today=business_date(now),
    )
    new = 0
    for values in plan.leads:
        statement = insert(SalesLead).values(**values, status="new")
        statement = statement.on_conflict_do_update(
            constraint="uq_sales_leads_fingerprint",
            set_={
                "title": statement.excluded.title,
                "summary": statement.excluded.summary,
                "score": statement.excluded.score,
                "signal_at": statement.excluded.signal_at,
                "payload": statement.excluded.payload,
                "updated_at": now,
            },
        ).returning(literal_column("(xmax = 0)"))
        # Decyzja handlowca (status, powód, przypisanie) zostaje przy powtórce.
        new += int(bool((await db.execute(statement)).scalar_one()))
    summary = {
        "checked_firms": report.checked_firms,
        "sent_firms": len(run.company_ids),
        "signals_in": len(report.signals),
        "leads": len(plan.leads),
        "leads_new": new,
        "without_owner": sum(1 for lead in plan.leads if not lead["assignee_user_id"]),
        "quiet": len({ref for ref in report.no_signal if ref in rows}),
        "dropped": {
            "outside_window": plan.outside_window,
            "nexus_clients": plan.nexus_clients,
            "not_eligible": plan.not_eligible,
            "unknown_company": plan.unknown_company,
            "duplicates": plan.duplicates,
        },
    }
    # Logi są publiczne: same liczby.
    logger.info(
        "sales_bot run=%s kind=winback signals=%d leads=%d new=%d",
        run.id,
        len(report.signals),
        len(plan.leads),
        new,
    )
    return summary


WINBACK = BotTask(
    kind="winback",
    task_text=_task_text,
    report_format=_report_format,
    report_model=WinbackReport,
    ingest=_ingest,
    lead_feedback=True,
)
