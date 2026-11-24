"""Haczyk przed telefonem: jedno zdanie otwarcia i do dwóch faktów ze źródłem.

Bieg rodzaju ``briefing`` z firmami w trybie ``call_hook`` (pętla
``tasks/sales_signals.py``, dzień roboczy od 16:00): firmy z kolejki dzwonienia na
następny dzień roboczy. Bot odsyła ``hooks`` w tym samym raporcie co punkty.

**Haczyk nie idzie do ``sales_company_briefings``**: ta tabela ma jeden wiersz na
firmę, więc haczyk nadpisałby punkty przed spotkaniem albo do prowadzonej szansy,
a jego kształt (zdanie + fakty) i tak jest inny niż punkty. Leży w
``sales_bot_results`` (rodzaj ``call_hook``, firma, ``payload``), jeden wiersz na
bieg i firmę; karta rozmowy pokazuje najnowszy nieodrzucony. Status zostaje
``new``: haczyk to podpowiedź do rozmowy, nie wynik do przyjęcia.

Reguły: ``docs/claude/sprzedaz/sygnaly-grok-bot.md`` („Haczyk i teczka”).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sales import SalesBotResult, SalesSignalRun
from app.services.sales.bot_tasks.base import (
    RequiredText,
    SourceUrl,
    result_fingerprint,
    save_results,
)

logger = logging.getLogger(__name__)

#: Tryb firmy w biegu ``briefing`` i rodzaj wyniku w ``sales_bot_results``.
CALL_HOOK = "call_hook"
MAX_HOOK_FIRMS = 40
MAX_FACTS = 2
#: Fakt do haczyka może być starszy niż sygnał (firma ogólnie), ale nie sprzed roku.
FACT_WINDOW_DAYS = 365
#: Firma z haczykiem młodszym niż to nie idzie do bota ponownie.
FRESH_FOR = timedelta(days=14)


class HookFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: RequiredText = Field(min_length=1, max_length=300)
    url: SourceUrl = Field(min_length=1, max_length=1000)
    published: date


class ReportHook(BaseModel):
    """Bez pól osób i kontaktów: zdanie i fakty o firmie, nic więcej."""

    model_config = ConfigDict(extra="forbid")

    company_ref: int
    sentence: RequiredText = Field(min_length=1, max_length=300)
    facts: list[HookFact] = Field(min_length=1, max_length=MAX_FACTS)


def hook_refs(run: SalesSignalRun) -> set[int]:
    allowed = {int(ref) for ref in run.company_ids}
    return {
        int(ref)
        for ref, mode in (run.modes or {}).items()
        if mode == CALL_HOOK and int(ref) in allowed
    }


#: Powód odrzucenia haczyka; wraca do bota w odpowiedzi na raport (``hooks_dropped``).
DROP_REASONS: dict[str, str] = {
    "not_call_hook_firm": 'Firma nie ma w tym biegu mode = "call_hook".',
    "duplicate": "Drugi haczyk dla tej samej firmy w raporcie.",
    "facts_outside_window": (
        "Żaden fakt nie ma daty publikacji z ostatnich 12 miesięcy (ani jutrzejszej)."
    ),
}


def plan_hooks(
    run: SalesSignalRun, hooks: list[ReportHook], *, today: date
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Wiersze do zapisu i odrzucone haczyki z powodem (``DROP_REASONS``)."""

    allowed = hook_refs(run)
    oldest = today - timedelta(days=FACT_WINDOW_DAYS)
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    dropped: list[dict[str, Any]] = []
    for hook in hooks:
        facts = [
            fact
            for fact in hook.facts
            if oldest <= fact.published <= today + timedelta(days=1)
        ]
        reason: Optional[str] = None
        if hook.company_ref not in allowed:
            reason = "not_call_hook_firm"
        elif hook.company_ref in seen:
            reason = "duplicate"
        elif not facts:
            reason = "facts_outside_window"
        if reason is not None:
            dropped.append(
                {
                    "company_ref": hook.company_ref,
                    "reason": reason,
                    "detail": DROP_REASONS[reason],
                }
            )
            continue
        seen.add(hook.company_ref)
        rows.append(
            {
                "company_id": hook.company_ref,
                "payload": {
                    "sentence": hook.sentence,
                    "facts": [
                        {
                            "text": fact.text,
                            "url": fact.url,
                            "published": fact.published.isoformat(),
                        }
                        for fact in facts
                    ],
                },
                "fingerprint": result_fingerprint(CALL_HOOK, hook.company_ref, run.id),
            }
        )
    return rows, dropped


async def save(
    db: AsyncSession,
    run: SalesSignalRun,
    hooks: list[ReportHook],
    *,
    today: date,
    now: datetime,
) -> dict[str, Any]:
    rows, dropped = plan_hooks(run, hooks, today=today)
    await save_results(db, run, rows, now, kind=CALL_HOOK)
    if dropped:
        # Logi są publiczne: same numery firm z biegu i kody powodów.
        logger.info(
            "sales_research call_hook run=%s dropped %s",
            run.id,
            ",".join(f"{item['company_ref']}:{item['reason']}" for item in dropped),
        )
    return {
        "hooks": len(rows),
        "hooks_dropped": dropped,
        "hook_saved_company_ids": sorted(row["company_id"] for row in rows),
    }


def task_text(refs: list[int]) -> str:
    return (
        f'Dla firm z mode = "call_hook" (ref {", ".join(map(str, refs))}) nie pisz '
        "punktów w briefings. Jutro albo w najbliższy dzień roboczy dzwoni do nich "
        "handlowiec z ofertą usług AI i automatyzacji. Dla każdej takiej firmy dopisz "
        "do hooks jedno zdanie otwarcia rozmowy (sentence, najwyżej 300 znaków), "
        "które nawiązuje do konkretnego faktu o firmie, i od 1 do "
        f"{MAX_FACTS} faktów (facts) z adresem źródła i datą publikacji. Fakty "
        "dotyczą firmy ogólnie oraz tego, jak używa automatyzacji, AI i IT "
        "(wdrożenia, programy, inwestycje, zespoły IT). Bierz informacje z ostatnich "
        "12 miesięcy. Zdanie niczego nie sprzedaje i nie obiecuje, tylko pokazuje, "
        "że wiemy, co się w firmie dzieje. Bez nazwisk osób. Firmę bez sprawdzonego "
        "faktu wpisz do no_signal, ale tylko jeśli faktycznie ją sprawdzono. W checked_firms "
        "podaj liczbę rzeczywiście sprawdzonych firm. Nie wpisuj firmy, której nie "
        "udało się sprawdzić."
    )


def report_format() -> dict[str, Any]:
    return {
        "company_ref": "<ref z firms, mode call_hook>",
        "sentence": "...",
        "facts": [{"text": "...", "url": "https://...", "published": "RRRR-MM-DD"}],
    }


async def fresh_company_ids(db: AsyncSession, *, now: datetime) -> set[int]:
    """Firmy z haczykiem młodszym niż ``FRESH_FOR`` (także odrzuconym)."""

    rows = await db.execute(
        select(SalesBotResult.company_id).where(
            SalesBotResult.kind == CALL_HOOK,
            SalesBotResult.company_id.is_not(None),
            SalesBotResult.updated_at >= now - FRESH_FOR,
        )
    )
    return {int(cid) for cid in rows.scalars()}


async def latest(db: AsyncSession, company_id: int) -> Optional[SalesBotResult]:
    """Najnowszy haczyk firmy; odrzucony przez handlowca się nie pokazuje."""

    return (
        await db.execute(
            select(SalesBotResult)
            .where(
                SalesBotResult.kind == CALL_HOOK,
                SalesBotResult.company_id == company_id,
                SalesBotResult.status != "rejected",
            )
            .order_by(SalesBotResult.updated_at.desc(), SalesBotResult.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
