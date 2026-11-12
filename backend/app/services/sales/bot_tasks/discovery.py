"""Rodzaj ``discovery`` („Nowe centra IT”, G-D): nowe i rosnące centra w Polsce.

Raz w miesiącu bot szuka bez listy firm (``needs_firms=False``) zapowiedzi
z ostatnich 6 miesięcy: nowe albo rozbudowywane centra IT, GBS, R&D i usług
wspólnych w Polsce. Do bota nie idzie nic z NEXUSA: ani firmy, ani ``request``.

Wynik do decyzji handlowca (``sales_bot_results``) z kartą z kartoteki, gdy ją
rozpoznamy: po domenie, potem po nazwie kanonicznej (ta sama reguła duplikatu co
przy zakładaniu karty), potem po marce (``company_aliases.brand_of``). Odcisk:
domena albo nazwa + link, więc kolejny bieg z tym samym ogłoszeniem nie cofa
decyzji.

„Załóż konto w Fabrykach IT” (``accept``) zakłada kartę, gdy jej nie ma, i szansę
w lejku ``atlas-it-factories`` na pierwszym etapie, z opiekunem = osobą, która
kliknęła, i wpisem w historii szansy. Karta z otwartym kontem w tym lejku nie
dostaje drugiego: wynik wskazuje istniejące.

Reguły: ``docs/claude/sprzedaz/sygnaly-grok-bot.md`` („Nowe centra IT”).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.sales import (
    SalesBotResult,
    SalesCompany,
    SalesOpportunity,
    SalesPipeline,
    SalesPipelineStage,
    SalesSignalRun,
)
from app.services.company_names import normalize_company_name
from app.services.sales import companies, history
from app.services.sales.bot_tasks.base import (
    AcceptRefused,
    BotTask,
    CleanText,
    RequiredText,
    SourceUrl,
    TaskContext,
    result_fingerprint,
    save_results,
)
from app.services.sales.company_aliases import brand_of
from app.services.sales.decision_map import IT_FACTORIES_PIPELINE_KEY
from app.services.sales.lifecycle import apply_stage

logger = logging.getLogger(__name__)

#: Zapowiedzi z ostatnich 6 miesięcy (decyzja Artura 12.11.2026).
WINDOW_DAYS = 183
MAX_ITEMS = 20
COMPANY_SOURCE = "bot:discovery"
NO_PIPELINE_DETAIL = "W NEXUSIE nie ma lejka Fabryki IT."
NO_STAGE_DETAIL = "Lejek Fabryki IT nie ma otwartego etapu."


class DiscoveryItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: RequiredText = Field(max_length=300)
    #: Domena firmy (nie serwisu, który napisał o centrum); bez niej dopasowanie po nazwie.
    domain: Optional[CleanText] = Field(default=None, max_length=255)
    city: CleanText = Field(default="", max_length=120)
    what: RequiredText = Field(max_length=500)
    scale: CleanText = Field(default="", max_length=300)
    why: CleanText = Field(default="", max_length=800)
    url: SourceUrl = Field(max_length=1000)
    published: date


class DiscoveryReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[DiscoveryItem] = Field(default_factory=list, max_length=MAX_ITEMS)


def _task_text(run: SalesSignalRun, ctx: TaskContext) -> str:
    return (
        "Lista firms jest pusta: szukasz sam. Znajdź zapowiedzi z ostatnich "
        f"{WINDOW_DAYS} dni o nowych albo rozbudowywanych centrach IT, GBS, R&D "
        "i usług wspólnych w Polsce (otwarcie, nowe biuro, rozbudowa zespołu, nowe "
        "kompetencje). Dla każdej podaj firmę (company), jej domenę (domain, nie "
        "domenę serwisu z artykułem; pomiń, gdy nie wiesz), miasto (city), co "
        "powstaje (what), skalę, jeśli źródło ją podaje, np. liczbę miejsc pracy "
        "(scale), jednym zdaniem, dlaczego to dobre konto dla firmy dostarczającej "
        "specjalistów IT (why), adres źródła (url) i datę publikacji (published). "
        f"Najwyżej {MAX_ITEMS} pozycji, jedna firma raz. Bez osób i kontaktów."
    )


def _report_format() -> dict[str, Any]:
    return {
        "items": [
            {
                "company": "...",
                "domain": "firma.pl",
                "city": "...",
                "what": "...",
                "scale": "...",
                "why": "...",
                "url": "https://...",
                "published": "RRRR-MM-DD",
            }
        ]
    }


# ── Dopasowanie karty ────────────────────────────────────────────────────


def clean_domain(value: Optional[str]) -> Optional[str]:
    """Domena firmy bez schematu, ``www`` i ścieżki; darmowa skrzynka to ``None``."""

    return companies.mail_domain(value)


def result_key(item: DiscoveryItem) -> str:
    """Domena albo nazwa kanoniczna: ta sama firma z kolejnego biegu ma ten sam klucz."""

    return (
        clean_domain(item.domain)
        or normalize_company_name(item.company)
        or (item.company.lower())
    )


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def match_card(
    db: AsyncSession, name: str, domain: Optional[str]
) -> tuple[Optional[SalesCompany], Optional[str]]:
    """Karta z kartoteki (poza archiwum) i sposób dopasowania: domena, nazwa, marka."""

    if domain:
        card = (
            await db.execute(
                select(SalesCompany)
                .where(
                    func.lower(SalesCompany.domain) == domain,
                    SalesCompany.archived_at.is_(None),
                )
                .order_by(SalesCompany.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if card is not None:
            return card, "domain"
    # Ta sama reguła duplikatu co przy zakładaniu karty (409 na ekranie Firmy).
    same = await companies.find_duplicates(db, name=name, nip=None)
    if same:
        return same[0], "name"
    canonical = normalize_company_name(name)
    if not canonical:
        return None, None
    brand = brand_of(canonical)
    rows = (
        await db.execute(
            select(SalesCompany)
            .where(
                SalesCompany.archived_at.is_(None),
                (SalesCompany.normalized_name == brand)
                | SalesCompany.normalized_name.like(
                    f"{_escape_like(brand)} %", escape="\\"
                ),
            )
            .order_by(SalesCompany.id)
            .limit(50)
        )
    ).scalars()
    for card in rows:
        if brand_of(card.normalized_name) == brand:
            return card, "brand"
    return None, None


# ── Zapis wyników ────────────────────────────────────────────────────────


def in_window(published: date, today: date) -> bool:
    return today - timedelta(days=WINDOW_DAYS) <= published <= today + timedelta(days=1)


async def _ingest(
    db: AsyncSession, run: SalesSignalRun, report: DiscoveryReport, now: datetime
) -> dict[str, Any]:
    today = business_date(now)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    outside_window = duplicates = matched = 0
    for item in report.items:
        if not in_window(item.published, today):
            outside_window += 1
            continue
        key = result_key(item)
        if key in seen:
            duplicates += 1
            continue
        seen.add(key)
        domain = clean_domain(item.domain)
        card, how = await match_card(db, item.company, domain)
        matched += int(card is not None)
        rows.append(
            {
                "company_id": card.id if card is not None else None,
                "payload": {
                    "company": item.company,
                    "domain": domain,
                    "city": item.city,
                    "what": item.what,
                    "scale": item.scale,
                    "why": item.why,
                    "url": item.url,
                    "published": item.published.isoformat(),
                    "match": how,
                },
                "fingerprint": result_fingerprint(run.kind, key, item.url),
            }
        )
    new = await save_results(db, run, rows, now)
    summary = {
        "items_in": len(report.items),
        "results": len(rows),
        "results_new": new,
        "in_base": matched,
        "dropped": {"outside_window": outside_window, "duplicates": duplicates},
    }
    # Logi są publiczne: same liczby.
    logger.info(
        "sales_bot run=%s kind=discovery items=%d results=%d new=%d in_base=%d",
        run.id,
        len(report.items),
        len(rows),
        new,
        matched,
    )
    return summary


# ── „Załóż konto w Fabrykach IT” ─────────────────────────────────────────


async def _pipeline(db: AsyncSession) -> tuple[SalesPipeline, SalesPipelineStage, list]:
    pipeline = (
        await db.execute(
            select(SalesPipeline).where(
                SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY,
                SalesPipeline.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if pipeline is None:
        raise AcceptRefused(NO_PIPELINE_DETAIL)
    stages = list(
        (
            await db.execute(
                select(SalesPipelineStage)
                .where(SalesPipelineStage.pipeline_id == pipeline.id)
                .order_by(SalesPipelineStage.position)
            )
        ).scalars()
    )
    stage = next((s for s in stages if s.outcome == "open"), None)
    if stage is None:
        raise AcceptRefused(NO_STAGE_DETAIL)
    return pipeline, stage, stages


async def _card(
    db: AsyncSession, result: SalesBotResult, user_id: int
) -> tuple[SalesCompany, bool]:
    payload = result.payload or {}
    name = str(payload.get("company") or "").strip()[:500]
    domain = clean_domain(payload.get("domain"))
    if result.company_id is not None:
        card = await db.get(SalesCompany, result.company_id)
        if card is not None and card.archived_at is None:
            return card, False
    # Karta mogła powstać albo zostać scalona od biegu: dopasowanie jeszcze raz.
    card, _how = await match_card(db, name, domain)
    if card is not None:
        return card, False
    if not name:
        raise AcceptRefused("Wynik nie ma nazwy firmy.")
    card = SalesCompany(
        name=name,
        normalized_name=normalize_company_name(name) or name.lower(),
        domain=domain,
        hq_city=(str(payload.get("city") or "").strip()[:120] or None),
        source=COMPANY_SOURCE,
        owner_user_id=user_id,
        created_by_user_id=user_id,
    )
    db.add(card)
    await db.flush()
    return card, True


async def _accept(
    db: AsyncSession, result: SalesBotResult, user_id: int, now: datetime
) -> dict[str, Any]:
    pipeline, stage, stages = await _pipeline(db)
    card, created = await _card(db, result, user_id)
    if card.owner_user_id is None:
        card.owner_user_id = user_id
    existing = (
        await db.execute(
            select(SalesOpportunity.id)
            .where(
                SalesOpportunity.company_id == card.id,
                SalesOpportunity.pipeline_id == pipeline.id,
                SalesOpportunity.status == "open",
                SalesOpportunity.archived_at.is_(None),
            )
            .order_by(SalesOpportunity.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if existing is None:
        payload = result.payload or {}
        description = " · ".join(
            part
            for part in (
                str(payload.get("what") or ""),
                str(payload.get("scale") or ""),
            )
            if part
        )
        opportunity = SalesOpportunity(
            company_id=card.id,
            pipeline_id=pipeline.id,
            stage_id=stage.id,
            title=card.name[:255],
            description=description or None,
            source=COMPANY_SOURCE,
            owner_user_id=user_id,
            created_by_user_id=user_id,
        )
        apply_stage(opportunity, stage, stages, now=now)
        db.add(opportunity)
        await db.flush()
        history.record_created(db, opportunity, user_id=user_id)
        opportunity_id = opportunity.id
    else:
        opportunity_id = existing
    result.company_id = card.id
    result.status = "accepted"
    result.decided_by_user_id = user_id
    result.decided_at = now
    result.updated_at = now
    logger.info(
        "sales_bot result=%s kind=discovery accepted company_created=%s existed=%s",
        result.id,
        created,
        existing is not None,
    )
    return {
        "opportunity_id": opportunity_id,
        "company_id": card.id,
        "company_created": created,
        "existed": existing is not None,
    }


DISCOVERY = BotTask(
    kind="discovery",
    task_text=_task_text,
    report_format=_report_format,
    report_model=DiscoveryReport,
    ingest=_ingest,
    needs_firms=False,
    accept=_accept,
)
