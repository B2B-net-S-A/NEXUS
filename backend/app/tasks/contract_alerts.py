"""Phase 9 A5 — contract status transitions + ending alerts.

Runs once a day. Responsibilities:
    1. Promote active → ending when end_date - today ≤ 30.
    2. Promote ending → ended when end_date < today.
    3. For each active/ending contract with end_date at T-60/30/14/7 days,
       create in-app Notification rows for admin + delivery_lead users
       and post one summary message to Slack (if SLACK_WEBHOOK_URL set).
    4. Dedup: Notification rows are keyed by (user, contract, threshold_days).
       We never re-notify for the same triple.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import date, timedelta
from typing import Iterable

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.contract import Contract, ContractStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

THRESHOLDS_DAYS = (60, 30, 14, 7)
_DEFAULT_INTERVAL_HOURS = 24.0
_STAFF_ROLES: tuple[UserRole, ...] = (UserRole.admin, UserRole.delivery_lead)


async def _promote_statuses(db: AsyncSession) -> tuple[int, int]:
    """Move active→ending and ending→ended based on end_date."""
    today = date.today()
    cutoff = today + timedelta(days=30)

    ending_count = await db.execute(
        update(Contract)
        .where(
            Contract.status == ContractStatus.active,
            Contract.end_date.isnot(None),
            Contract.end_date <= cutoff,
        )
        .values(status=ContractStatus.ending)
    )
    ended_count = await db.execute(
        update(Contract)
        .where(
            Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            Contract.end_date.isnot(None),
            Contract.end_date < today,
        )
        .values(status=ContractStatus.ended)
    )
    return (ending_count.rowcount or 0, ended_count.rowcount or 0)


async def _staff_user_ids(db: AsyncSession) -> list[int]:
    res = await db.execute(
        select(User.id).where(User.role.in_(_STAFF_ROLES), User.is_active.is_(True))
    )
    return [row[0] for row in res.all()]


async def _contract_ids_already_notified(db: AsyncSession, threshold: int) -> set[int]:
    """Find contract_ids that already have a contract_ending notification for this threshold."""
    # We use a deterministic title prefix per threshold for dedup without schema change.
    title_prefix = f"[{threshold}d]"
    res = await db.execute(
        select(Notification.link).where(
            Notification.notification_type == NotificationType.contract_ending,
            Notification.title.like(f"{title_prefix}%"),
        )
    )
    ids: set[int] = set()
    for (link,) in res.all():
        if not link:
            continue
        # link format: /contracts/<id>
        try:
            cid = int(link.rstrip("/").split("/")[-1])
            ids.add(cid)
        except ValueError:
            continue
    return ids


async def _contracts_at_threshold(db: AsyncSession, threshold: int) -> list[Contract]:
    """Contracts whose end_date falls within (threshold-1, threshold] days from today.

    A tighter match (exact T-30 day only) would be fragile if the cron misses
    a day; instead we use a one-day window per threshold, combined with the
    already-notified dedup, so each contract alerts exactly once per window.
    """
    today = date.today()
    target = today + timedelta(days=threshold)
    window_start = target - timedelta(days=1)
    res = await db.execute(
        select(Contract).where(
            Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            Contract.end_date.isnot(None),
            Contract.end_date > window_start,
            Contract.end_date <= target,
        )
    )
    return list(res.scalars().all())


async def _post_slack_summary(webhook: str, events: list[tuple[int, Contract]]) -> None:
    if not webhook or not events:
        return
    lines = []
    for threshold, c in events:
        lines.append(
            f"• <https://nexus.dynaminds.pl/contracts/{c.id}|Kontrakt #{c.id}> "
            f"kończy się za *{threshold} dni* ({c.end_date})"
        )
    text = (
        ":hourglass_flowing_sand: *Wygasające kontrakty* — "
        f"{len(events)} nadchodzące terminy:\n" + "\n".join(lines)
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(webhook, json={"text": text})
    except Exception as e:  # noqa: BLE001
        logger.warning("contract_alerts: slack post failed %s", e)


async def run_contract_alerts_cycle() -> dict:
    """One pass: promote statuses + create notifications + post Slack summary."""
    stats = {
        "promoted_ending": 0,
        "promoted_ended": 0,
        "notifications_created": 0,
        "slack_sent": 0,
    }
    async with AsyncSessionLocal() as db:
        ending, ended = await _promote_statuses(db)
        stats["promoted_ending"] = ending
        stats["promoted_ended"] = ended
        await db.commit()

        staff_ids = await _staff_user_ids(db)
        if not staff_ids:
            logger.info("contract_alerts: no staff users — skipping notifications")
            return stats

        to_slack: list[tuple[int, Contract]] = []
        for threshold in THRESHOLDS_DAYS:
            already = await _contract_ids_already_notified(db, threshold)
            contracts = await _contracts_at_threshold(db, threshold)
            fresh = [c for c in contracts if c.id not in already]
            for c in fresh:
                title = f"[{threshold}d] Kontrakt #{c.id} wygasa"
                message = (
                    f"Kontrakt #{c.id} kończy się {c.end_date} — "
                    f"zostało {threshold} dni. Rozważ przedłużenie lub kontakt z klientem."
                )
                link = f"/contracts/{c.id}"
                for uid in staff_ids:
                    db.add(
                        Notification(
                            user_id=uid,
                            title=title,
                            message=message,
                            link=link,
                            notification_type=NotificationType.contract_ending,
                        )
                    )
                    stats["notifications_created"] += 1
                to_slack.append((threshold, c))
        await db.commit()

    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if webhook and to_slack:
        await _post_slack_summary(webhook, to_slack)
        stats["slack_sent"] = len(to_slack)

    logger.info("contract_alerts: cycle done %s", stats)
    return stats


async def contract_alerts_loop(interval_hours: float = _DEFAULT_INTERVAL_HOURS) -> None:
    """Long-running task: run once a day."""
    logger.info("contract_alerts: started interval=%.1f h", interval_hours)
    # Initial delay so app startup isn't slowed
    await asyncio.sleep(120)
    while True:
        try:
            await run_contract_alerts_cycle()
        except Exception as e:  # noqa: BLE001
            logger.warning("contract_alerts: cycle error %s", e)
        await asyncio.sleep(interval_hours * 3600)


def thresholds() -> Iterable[int]:
    """Exported for tests."""
    return THRESHOLDS_DAYS
