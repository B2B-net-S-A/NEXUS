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


async def run_notification_backlog_repair(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> Optional[dict[str, Any]]:
    """Oznacza stare wpisy jako przeczytane. ``None`` = już wykonane.

    Wołający commituje.
    """
    now = now or datetime.now(timezone.utc)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": REPAIR_MARKER}
    )
    if await db.get(AppSetting, REPAIR_MARKER) is not None:
        return None

    cutoff = now - timedelta(days=AGE_DAYS)
    stale = (
        Notification.is_read.is_(False),
        Notification.notification_type.in_(TYPES),
        Notification.created_at < cutoff,
    )
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
    db.add(AppSetting(key=REPAIR_MARKER, value=summary))
    await db.flush()
    return summary


__all__ = ["AGE_DAYS", "REPAIR_MARKER", "TYPES", "run_notification_backlog_repair"]
