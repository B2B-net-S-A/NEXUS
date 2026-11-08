"""Porcja zespołu dziś dla HoR (audyt 08.11.2026, P8).

Bez tego widoku nie da się ocenić, czy minimum jest osiągalne: kto zrobił ile
decyzji, kiedy doszedł do minimum, jaki ma podział S:O i ile razy trafił na 423.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.user import User
from app.services import review_batch as rb

GOOD_BEFORE = time(11, 0)


def minimum_reached_at(
    counted: tuple[datetime, ...], required: int
) -> Optional[datetime]:
    """Chwila, w której osoba doszła do wymaganej liczby decyzji."""
    if required <= 0 or len(counted) < required:
        return None
    return counted[required - 1]


async def _blocks_today(
    db: AsyncSession, user_ids: list[int], since: datetime
) -> dict[int, int]:
    if not user_ids:
        return {}
    rows = await db.execute(
        select(Activity.user_id, func.count(Activity.id))
        .where(
            Activity.entity_type == rb.BLOCK_ENTITY,
            Activity.action == rb.BLOCK_ACTION,
            Activity.user_id.in_(user_ids),
            Activity.created_at >= since,
        )
        .group_by(Activity.user_id)
    )
    return {int(uid): int(count) for uid, count in rows.all()}


async def team_view(db: AsyncSession, *, now: datetime) -> dict:
    value = await rb.read_settings(db)
    users = sorted(
        (
            u
            for u in (
                await db.scalars(select(User).where(User.is_active.is_(True)))
            ).all()
            if rb.applies_to(u)
        ),
        key=lambda u: (u.name or u.email or "").lower(),
    )
    ids = [u.id for u in users]
    since = rb.day_start(now)
    decisions = await rb._decisions(db, ids, now=now)
    absent = await rb.absent_today(db, ids)
    blocks = await _blocks_today(db, ids, since)
    zone = ZoneInfo(settings.BUSINESS_TZ)
    rows = []
    good = 0
    measured = 0
    for user in users:
        counts = rb.summarize_day(decisions.get(user.id, []), since)
        cards = [] if user.id in absent else await rb._own_cards(db, user.id, now=now)
        required = min(value.minimum, counts.done + len(cards) + counts.open_today)
        reached = minimum_reached_at(counts.counted_times, required)
        local = reached.astimezone(zone) if reached is not None else None
        if user.id not in absent and required > 0:
            measured += 1
            if local is not None and local.time() < GOOD_BEFORE:
                good += 1
        rows.append(
            {
                "user_id": user.id,
                "name": user.name or user.email or str(user.id),
                "absent": user.id in absent,
                "done_today": counts.done,
                "required": required,
                "pending": len(cards),
                "minimum_at": local.strftime("%H:%M") if local is not None else None,
                "screened": counts.screened_today,
                "rejected": counts.rejected_today,
                "open_screenings": counts.open_screenings,
                "blocked_today": blocks.get(user.id, 0),
            }
        )
    return {
        "day": since.astimezone(zone).date().isoformat(),
        "enabled": rb.enabled(),
        "minimum": value.minimum,
        "rows": rows,
        "good_before_11": good,
        "measured": measured,
    }
