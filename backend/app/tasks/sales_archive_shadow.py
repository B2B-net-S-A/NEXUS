"""Automat archiwizacji szans w trybie cienia: liczy, nie archiwizuje.

Raz dziennie sprawdza, co by zarchiwizował: szansa otwarta, bez przyszłego kroku,
dotyk (``services/sales/touch.py``) starszy niż 90 dni, poza lejkami Fabryki IT
i Przetargi, bez tagu ``top22``, bez ``keep_open_until`` w przyszłości.

Transakcja jest tylko do odczytu, bo włączenie prawdziwej archiwizacji to osobna
decyzja Artura. Wynik to jedna linia logu z samymi liczbami: logi są publiczne,
więc bez nazwisk, firm i kwot. → docs/claude/sprzedaz/sprzedaz-w-nexusie-decyzje-i-reguly.md
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import and_, exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now, seconds_until_local_time
from app.models.sales import SalesActivity, SalesOpportunity, SalesPipeline
from app.services import loop_heartbeat
from app.services import sales_schema as schema
from app.services.sales.decision_map import IT_FACTORIES_PIPELINE_KEY
from app.services.sales.touch import last_touch_at, not_cancelled

logger = logging.getLogger(__name__)

STALE_AFTER_DAYS = 90
EXCLUDED_PIPELINE_KEYS = frozenset({IT_FACTORIES_PIPELINE_KEY, "atlas-tenders"})
KEEP_OPEN_TAG = "top22"
RUN_HOUR_LOCAL = 4
RUN_MINUTE_LOCAL = 40

#: Kolejność jak w log-linii; szansa wpada do pierwszego pasującego powodu.
REASONS = ("excluded_pipeline", "top22", "keep_open", "has_step", "fresh", "candidate")


def _has_future_step(now: datetime):
    """Zadanie albo telefon z przyszłym terminem, przyszłe spotkanie firmy."""

    activity = SalesActivity
    opportunity = SalesOpportunity
    of_opportunity = activity.opportunity_id == opportunity.id
    return (
        exists()
        .where(
            or_(
                and_(
                    or_(
                        of_opportunity,
                        and_(
                            activity.company_id == opportunity.company_id,
                            activity.opportunity_id.is_(None),
                        ),
                    ),
                    activity.kind.in_(schema.TASK_KINDS),
                    activity.done_at.is_(None),
                    activity.due_at > now,
                ),
                and_(
                    or_(of_opportunity, activity.company_id == opportunity.company_id),
                    activity.kind == "meeting",
                    activity.occurred_at > now,
                    *not_cancelled(),
                ),
            )
        )
        .correlate(opportunity)
    )


async def classify_open_opportunities(
    db: AsyncSession, *, now: datetime, today: date
) -> dict[int, str]:
    """Id otwartej szansy → powód z ``REASONS``. Niczego nie zapisuje."""

    rows = await db.execute(
        select(
            SalesOpportunity.id,
            SalesPipeline.key,
            SalesOpportunity.tags,
            SalesOpportunity.keep_open_until,
            last_touch_at(now).label("touch"),
            _has_future_step(now).label("has_step"),
        )
        .join(SalesPipeline, SalesPipeline.id == SalesOpportunity.pipeline_id)
        .where(
            SalesOpportunity.status == "open",
            SalesOpportunity.archived_at.is_(None),
        )
    )
    stale_before = now - timedelta(days=STALE_AFTER_DAYS)
    reasons: dict[int, str] = {}
    for row in rows:
        if row.key in EXCLUDED_PIPELINE_KEYS:
            reason = "excluded_pipeline"
        elif KEEP_OPEN_TAG in (row.tags or []):
            reason = "top22"
        elif row.keep_open_until is not None and row.keep_open_until >= today:
            reason = "keep_open"
        elif row.has_step:
            reason = "has_step"
        elif row.touch >= stale_before:
            reason = "fresh"
        else:
            reason = "candidate"
        reasons[row.id] = reason
    return reasons


async def run_once() -> Counter[str]:
    now = local_now()
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        reasons = await classify_open_opportunities(db, now=now, today=now.date())
    counts = Counter(reasons.values())
    numbers = " ".join(f"{reason}={counts[reason]}" for reason in REASONS)
    logger.info("sales_archive_shadow open=%d %s", len(reasons), numbers)
    return counts


async def sales_archive_shadow_loop() -> None:
    if not settings.SALES_ARCHIVE_SHADOW_ENABLED:
        logger.info("sales_archive_shadow_loop disabled")
        return
    beat = loop_heartbeat.register(
        "sales_archive_shadow", max_silence_seconds=27 * 3600
    )
    while True:
        beat.tick()
        delay = seconds_until_local_time(local_now(), RUN_HOUR_LOCAL, RUN_MINUTE_LOCAL)
        await asyncio.sleep(max(delay, 60.0))
        beat.tick()
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("sales_archive_shadow_loop iteration failed")
