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


def plan_hooks(
    run: SalesSignalRun, hooks: list[ReportHook], *, today: date
) -> tuple[list[dict[str, Any]], int]:
    """Wiersze do zapisu i liczba odrzuconych (firma spoza trybu, drugi raz, bez faktu)."""

    allowed = hook_refs(run)
    oldest = today - timedelta(days=FACT_WINDOW_DAYS)
    rows: list[dict[str, Any]] = []
    seen: set[int] = set()
    dropped = 0
    for hook in hooks:
        facts = [
            fact
            for fact in hook.facts
            if oldest <= fact.published <= today + timedelta(days=1)
        ]
        if hook.company_ref not in allowed or hook.company_ref in seen or not facts:
            dropped += 1
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
) -> dict[str, int]:
    rows, dropped = plan_hooks(run, hooks, today=today)
    await save_results(db, run, rows, now, kind=CALL_HOOK)
    return {"hooks": len(rows), "hooks_dropped": dropped}


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
        "faktu pomiń."
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
