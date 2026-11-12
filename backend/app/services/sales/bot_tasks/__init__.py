"""Rejestr zadań bota researchu (Grok Bot): rodzaj biegu → ``BotTask``.

Dodanie rodzaju: moduł w tym pakiecie z ``BotTask`` (wzór i zasady w ``base.py``)
i wpis w ``REGISTRY``. Rodzaj musi być w ``sales_schema.BOT_RUN_KINDS`` (CHECK
w bazie). Rodzaje spoza ``LEGACY_KINDS`` startują tylko przy włączonej fladze
``SALES_BOT_TASKS_ENABLED``. Nieznany rodzaj: start i przyjęcie raportu odmawiają.

Reguły: ``docs/claude/sprzedaz/sygnaly-grok-bot.md`` („Zadania bota”).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.sales import SalesSignalRun
from app.services.sales.bot_tasks import people, signals_briefing
from app.services.sales.bot_tasks.base import (
    AcceptRefused,
    BotTask,
    CleanText,
    RequiredText,
    SourceUrl,
    TaskContext,
    mark_received,
    numbers_only,
    result_fingerprint,
    save_results,
)

__all__ = [
    "AcceptRefused",
    "BotTask",
    "CleanText",
    "LEGACY_KINDS",
    "REGISTRY",
    "RequiredText",
    "SourceUrl",
    "TaskContext",
    "allowed_to_start",
    "enabled",
    "get",
    "ingest",
    "numbers_only",
    "result_fingerprint",
    "save_results",
]

logger = logging.getLogger(__name__)

#: Rodzaje z 0676, które działają bez flagi zadań (rutyna v1 zna tylko je).
LEGACY_KINDS: frozenset[str] = frozenset({"signals", "briefing"})

REGISTRY: dict[str, BotTask] = {
    task.kind: task
    for task in (signals_briefing.SIGNALS, signals_briefing.BRIEFING, people.PEOPLE)
}


def enabled() -> bool:
    return bool(settings.SALES_BOT_TASKS_ENABLED)


def get(kind: str) -> Optional[BotTask]:
    return REGISTRY.get(kind)


def allowed_to_start(kind: str) -> bool:
    """Rodzaj z rejestru; nowe rodzaje dopiero przy włączonej fladze."""

    return kind in REGISTRY and (kind in LEGACY_KINDS or enabled())


async def ingest(
    db: AsyncSession, task: BotTask, run: SalesSignalRun, report: Any, *, now: datetime
) -> dict[str, Any]:
    """Zapis raportu przez rodzaj, potem bieg jako przyjęty (token zużyty)."""

    summary = await task.ingest(db, run, report, now)
    mark_received(run, summary, now)
    # Logi są publiczne: rodzaj i numer biegu, bez treści raportu.
    logger.info("sales_bot run=%s kind=%s received", run.id, run.kind)
    return summary
