"""Jednorazowe oznaczenie starych powiadomień jako przeczytane (04.10.2026).

Przegląd pulpitu z 04.10.2026: mediana nieprzeczytanych powiadomień wynosiła
319 u rekrutera, 568 u Delivery Leada i 13 339 u Head of Recruitment. Około
33 tys. z nich to cztery typy, które od tygodni nic nie wnoszą: „etap stoi
6 h” (28 621), „coach KPI”, „etap stoi 7 dni” i raport PowerCalling. Przy takim
tle licznik nieprzeczytanych nic nie mówi, a nowe powiadomienie ginie.

Decyzja Artura 04.10.2026: oznaczyć jako przeczytane nieprzeczytane wpisy tych
typów starsze niż ``AGE_DAYS`` dni. Nic nie jest kasowane; świeże wpisy
(„etap stoi” wciąż może powstać) zostają nieprzeczytane.

Marker w ``app_settings`` + advisory lock: drugi start kończy się od razu.
Paragon niesie wyłącznie liczby per typ.

16.10.2026 (ikony paska zamiast dzwonka, decyzja D5): drugie, szersze
sprzątanie — :func:`run_topics_backlog_repair`, każdy typ nieprzeczytany
dłużej niż ``TOPICS_AGE_DAYS`` dni. Okienko „Rekrutacje” i tak pokazuje
tylko tydzień, a licznik „CV” liczy się ze stanu; stary zapas zostałby
w ``/notifications/count`` i w nieprzeczytanych czatach na zawsze.
Maili nie dotyka: zapas maila czatu patrzy na minuty, kolejka na 24 h.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.notification import Notification, NotificationType

REPAIR_MARKER = "notification_backlog_read_2026_10"
AGE_DAYS = 14
TYPES: tuple[NotificationType, ...] = (
    NotificationType.dl_stage_stale_6h,
    NotificationType.stage_stuck_7d,
    NotificationType.kpi_coach,
    NotificationType.powercalling_kpi,
)

TOPICS_REPAIR_MARKER = "notification_topics_backlog_read_2026_10"
TOPICS_AGE_DAYS = 7


async def run_notification_backlog_repair(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> Optional[dict[str, Any]]:
    """Oznacza stare wpisy czterech typów jako przeczytane. ``None`` = już
    wykonane. Wołający commituje.
    """
    return await _mark_stale_read(
        db, marker=REPAIR_MARKER, age_days=AGE_DAYS, types=TYPES, now=now
    )


async def run_topics_backlog_repair(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> Optional[dict[str, Any]]:
    """Każdy typ nieprzeczytany dłużej niż tydzień → przeczytany (16.10.2026).
    ``None`` = już wykonane. Wołający commituje.
    """
    return await _mark_stale_read(
        db, marker=TOPICS_REPAIR_MARKER, age_days=TOPICS_AGE_DAYS, types=None, now=now
    )


async def _mark_stale_read(
    db: AsyncSession,
    *,
    marker: str,
    age_days: int,
    types: Optional[tuple[NotificationType, ...]],
    now: Optional[datetime],
) -> Optional[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": marker}
    )
    if await db.get(AppSetting, marker) is not None:
        return None

    cutoff = now - timedelta(days=age_days)
    stale = [
        Notification.is_read.is_(False),
        Notification.created_at < cutoff,
    ]
    if types is not None:
        stale.append(Notification.notification_type.in_(types))
    counts = {
        str(getattr(kind, "value", kind)): int(n)
        for kind, n in (
            await db.execute(
                select(Notification.notification_type, func.count(Notification.id))
                .where(*stale)
                .group_by(Notification.notification_type)
            )
        ).all()
    }
    await db.execute(
        update(Notification)
        .where(*stale)
        .values(is_read=True)
        .execution_options(synchronize_session=False)
    )
    summary = {
        "done_at": now.isoformat(),
        "cutoff": cutoff.isoformat(),
        "marked_read": counts,
        "total": sum(counts.values()),
    }
    db.add(AppSetting(key=marker, value=summary))
    await db.flush()
    return summary


__all__ = [
    "AGE_DAYS",
    "REPAIR_MARKER",
    "TOPICS_AGE_DAYS",
    "TOPICS_REPAIR_MARKER",
    "TYPES",
    "run_notification_backlog_repair",
    "run_topics_backlog_repair",
]
