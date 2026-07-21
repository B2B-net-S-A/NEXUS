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
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.contract import Contract, ContractStatus
from app.models.contract_alert_dedup import ContractAlertDedup
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.contract_equipment import ContractEquipment, EquipmentReturnStatus
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole

logger = logging.getLogger(__name__)

# 90d is a "heads-up, start the extension conversation" ping; tighter
# thresholds stay as urgent reminders.
THRESHOLDS_DAYS = (90, 60, 30, 14, 7)
EQUIPMENT_RETURN_THRESHOLD_DAYS = 14
CLIENT_ORDER_THRESHOLD_DAYS = 30
COMPLIANCE_THRESHOLD_DAYS = 30
_COMPLIANCE_DOC_TYPES = (
    ContractDocumentType.nip,
    ContractDocumentType.zus_certificate,
    ContractDocumentType.oc_policy,
)
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


async def _claim_alert(db: AsyncSession, dedup_key: str) -> bool:
    """Atomically claim a dedup key. ``INSERT ... ON CONFLICT DO NOTHING``.

    Returns ``True`` if THIS pass inserted the row (fresh — go create the
    notifications), ``False`` if the key was already claimed (skip). The
    ``_already_notified`` SELECT helpers stay as a cheap pre-filter (and keep
    all-time dedup semantics across the pre-ledger transition), but they are
    NOT atomic on their own: two overlapping / concurrent loop passes (restart,
    multi-worker) could both pass the SELECT before either committed and then
    insert DUPLICATE notifications. This claim closes that race — the UNIQUE
    constraint serializes the two passes so exactly one wins the key. The claim
    is committed in the SAME transaction as the notifications, so a rollback
    drops both together.
    """
    stmt = (
        pg_insert(ContractAlertDedup)
        .values(dedup_key=dedup_key)
        .on_conflict_do_nothing(constraint="uq_contract_alert_dedup_key")
        .returning(ContractAlertDedup.id)
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


def _end_date_from_title(title: str | None) -> str | None:
    """Pull the ISO deadline encoded as ``[Nd|YYYY-MM-DD]`` from an ending-alert title.

    Returns ``None`` for legacy ``[Nd]`` titles that carry no deadline — those never
    match an episode, so a contract still inside a window at ship time may re-alert
    once (an acceptable one-off, not a silent gap).
    """
    if not title or not title.startswith("["):
        return None
    close = title.find("]")
    if close == -1:
        return None
    _, sep, end_iso = title[1:close].partition("|")  # "30d|2026-09-01" -> "2026-09-01"
    if not sep:
        return None
    return end_iso.strip() or None


async def _contract_ids_already_notified(
    db: AsyncSession, threshold: int
) -> set[tuple[int, str]]:
    """Return ``(contract_id, end_date_iso)`` episodes already alerted at this threshold.

    Episode-aware dedup (P1-NOTIFY-01): the title encodes the current deadline as
    ``[Nd|<end_date>]``, so a bulk-extend to a new ``end_date`` is a NEW episode — the
    pair no longer matches and every threshold re-arms. A contract counts as
    already-notified for a threshold ONLY when a prior ``[Nd]`` notification exists for
    the SAME end_date (keyed without a schema change).
    """
    # Prefix without the closing bracket so both legacy ``[Nd]`` and new ``[Nd|..]``
    # titles are fetched; legacy rows then drop out via the None end_date parse.
    title_prefix = f"[{threshold}d"
    res = await db.execute(
        select(Notification.link, Notification.title).where(
            Notification.notification_type == NotificationType.contract_ending,
            Notification.title.like(f"{title_prefix}%"),
        )
    )
    episodes: set[tuple[int, str]] = set()
    for link, title in res.all():
        if not link:
            continue
        end_iso = _end_date_from_title(title)
        if end_iso is None:
            continue
        # link format: /contracts/<id>
        try:
            cid = int(link.rstrip("/").split("/")[-1])
        except ValueError:
            continue
        episodes.add((cid, end_iso))
    return episodes


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


async def _post_slack_summary(webhook: str, events: list[tuple[int, Contract]]) -> bool:
    """Post the expiry summary to Slack. Returns ``True`` only on a 2xx response.

    httpx does not raise on 4xx/5xx by default, so a failed webhook must never be
    counted as sent (mirrors ``slack_sla_alerts._post_to_slack``). On an HTTP error
    status or a transport error we log a warning and return ``False`` so the caller
    leaves ``stats['slack_sent']`` at 0.
    """
    if not webhook or not events:
        return False
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
            resp = await client.post(webhook, json={"text": text})
            resp.raise_for_status()
    except Exception as e:  # noqa: BLE001
        logger.warning("contract_alerts: slack post failed %s", e)
        return False
    return True


async def _compliance_documents_expiring(db: AsyncSession) -> list[ContractDocument]:
    """Return NIP/OC/ZUS docs whose expiry_date is within COMPLIANCE_THRESHOLD_DAYS."""
    today = date.today()
    cutoff = today + timedelta(days=COMPLIANCE_THRESHOLD_DAYS)
    res = await db.execute(
        select(ContractDocument).where(
            ContractDocument.doc_type.in_(_COMPLIANCE_DOC_TYPES),
            ContractDocument.expiry_date.isnot(None),
            ContractDocument.expiry_date <= cutoff,
            ContractDocument.expiry_date >= today,
        )
    )
    return list(res.scalars().all())


async def _compliance_already_notified(db: AsyncSession) -> set[int]:
    """Find contract_document ids already reported."""
    res = await db.execute(
        select(Notification.message).where(
            Notification.notification_type == NotificationType.contract_ending,
            Notification.title.like("[compliance]%"),
        )
    )
    ids: set[int] = set()
    for (msg,) in res.all():
        # Message encodes the doc id in the form 'doc_id=<N>'
        if not msg:
            continue
        for tok in msg.split():
            if tok.startswith("doc_id="):
                try:
                    ids.add(int(tok.split("=", 1)[1].rstrip(".")))
                except ValueError:
                    pass
    return ids


async def _equipment_due_for_return(db: AsyncSession) -> list[ContractEquipment]:
    today = date.today()
    cutoff = today + timedelta(days=EQUIPMENT_RETURN_THRESHOLD_DAYS)
    res = await db.execute(
        select(ContractEquipment).where(
            ContractEquipment.return_status == EquipmentReturnStatus.pending,
            ContractEquipment.return_due_date.isnot(None),
            ContractEquipment.return_due_date <= cutoff,
        )
    )
    return list(res.scalars().all())


async def _equipment_already_notified(db: AsyncSession) -> set[int]:
    res = await db.execute(
        select(Notification.related_entity_id).where(
            Notification.notification_type == NotificationType.equipment_return_due_14d,
            Notification.related_entity_type == "contract_equipment",
        )
    )
    return {row[0] for row in res.all() if row[0] is not None}


async def _client_orders_ending(db: AsyncSession) -> list[Contract]:
    today = date.today()
    cutoff = today + timedelta(days=CLIENT_ORDER_THRESHOLD_DAYS)
    res = await db.execute(
        select(Contract).where(
            Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            Contract.client_order_end_date.isnot(None),
            Contract.client_order_end_date <= cutoff,
            Contract.client_order_end_date >= today,
        )
    )
    return list(res.scalars().all())


async def _client_order_already_notified(db: AsyncSession) -> set[int]:
    res = await db.execute(
        select(Notification.related_entity_id).where(
            Notification.notification_type == NotificationType.client_order_ending_30d,
            Notification.related_entity_type == "contract",
        )
    )
    return {row[0] for row in res.all() if row[0] is not None}


async def run_contract_alerts_cycle() -> dict:
    """One pass: promote statuses + create notifications + post Slack summary."""
    stats = {
        "promoted_ending": 0,
        "promoted_ended": 0,
        "notifications_created": 0,
        "compliance_alerts": 0,
        "equipment_return_alerts": 0,
        "client_order_alerts": 0,
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
            # Episode-aware: a contract re-alerts once its CURRENT deadline forms a
            # new (id, end_date) pair — bulk-extend to a fresh end_date re-arms it.
            fresh = [
                c for c in contracts if (c.id, c.end_date.isoformat()) not in already
            ]
            notif_type = (
                NotificationType.contract_ending_90d
                if threshold == 90
                else NotificationType.contract_ending
            )
            for c in fresh:
                # Claim key carries the end_date too, so the atomic ledger re-arms on
                # extend just like the SELECT pre-filter above.
                if not await _claim_alert(
                    db, f"ending:{threshold}:{c.id}:{c.end_date.isoformat()}"
                ):
                    continue
                title = (
                    f"[{threshold}d|{c.end_date.isoformat()}] Kontrakt #{c.id} wygasa"
                )
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
                            notification_type=notif_type,
                            related_entity_type="contract",
                            related_entity_id=c.id,
                        )
                    )
                    stats["notifications_created"] += 1
                to_slack.append((threshold, c))
        await db.commit()

    # Compliance: NIP / OC / ZUS expiring soon
    async with AsyncSessionLocal() as db:
        staff_ids_res = await db.execute(
            select(User.id).where(User.role.in_(_STAFF_ROLES), User.is_active.is_(True))
        )
        staff_ids = [row[0] for row in staff_ids_res.all()]
        if staff_ids:
            expiring = await _compliance_documents_expiring(db)
            already = await _compliance_already_notified(db)
            fresh = [d for d in expiring if d.id not in already]
            for doc in fresh:
                if not await _claim_alert(db, f"compliance:{doc.id}"):
                    continue
                title = f"[compliance] Dokument #{doc.id} wygasa"
                message = (
                    f"Dokument {doc.doc_type.value} (doc_id={doc.id}) kontraktu "
                    f"#{doc.contract_id} wygasa {doc.expiry_date}. "
                    f"Zamów nowy zanim straci ważność."
                )
                for uid in staff_ids:
                    db.add(
                        Notification(
                            user_id=uid,
                            title=title,
                            message=message,
                            link=f"/contracts/{doc.contract_id}",
                            notification_type=NotificationType.contract_ending,
                        )
                    )
                stats["compliance_alerts"] += 1
        await db.commit()

    # Equipment returns due within 14 days.
    async with AsyncSessionLocal() as db:
        staff_ids_res = await db.execute(
            select(User.id).where(User.role.in_(_STAFF_ROLES), User.is_active.is_(True))
        )
        staff_ids = [row[0] for row in staff_ids_res.all()]
        if staff_ids:
            due = await _equipment_due_for_return(db)
            already = await _equipment_already_notified(db)
            fresh = [item for item in due if item.id not in already]
            for item in fresh:
                if not await _claim_alert(db, f"equipment:{item.id}"):
                    continue
                days_left = (
                    (item.return_due_date - date.today()).days
                    if item.return_due_date
                    else None
                )
                title = f"[eq_ret] Sprzęt do zwrotu — item #{item.id}"
                message = (
                    f"Sprzęt {item.item_type.value} "
                    f"(serial={item.serial_number or '—'}) z kontraktu "
                    f"#{item.contract_id} ma być zwrócony "
                    f"{item.return_due_date} ({days_left} dni)."
                )
                for uid in staff_ids:
                    db.add(
                        Notification(
                            user_id=uid,
                            title=title,
                            message=message,
                            link=f"/contracts/{item.contract_id}",
                            notification_type=NotificationType.equipment_return_due_14d,
                            related_entity_type="contract_equipment",
                            related_entity_id=item.id,
                        )
                    )
                stats["equipment_return_alerts"] += 1
        await db.commit()

    # Client orders expiring in 30 days (often earlier than the consultant contract).
    async with AsyncSessionLocal() as db:
        staff_ids_res = await db.execute(
            select(User.id).where(User.role.in_(_STAFF_ROLES), User.is_active.is_(True))
        )
        staff_ids = [row[0] for row in staff_ids_res.all()]
        if staff_ids:
            orders = await _client_orders_ending(db)
            already = await _client_order_already_notified(db)
            fresh = [c for c in orders if c.id not in already]
            for c in fresh:
                if not await _claim_alert(db, f"client_order:{c.id}"):
                    continue
                days_left = (
                    (c.client_order_end_date - date.today()).days
                    if c.client_order_end_date
                    else None
                )
                title = (
                    f"[client_order] Kontrakt #{c.id} — zamówienie klienta kończy się"
                )
                message = (
                    f"Zamówienie klienta dla kontraktu #{c.id} wygasa "
                    f"{c.client_order_end_date} ({days_left} dni). "
                    f"Skontaktuj się z klientem w sprawie przedłużenia."
                )
                for uid in staff_ids:
                    db.add(
                        Notification(
                            user_id=uid,
                            title=title,
                            message=message,
                            link=f"/contracts/{c.id}",
                            notification_type=NotificationType.client_order_ending_30d,
                            related_entity_type="contract",
                            related_entity_id=c.id,
                        )
                    )
                stats["client_order_alerts"] += 1
        await db.commit()

    webhook = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if webhook and to_slack and await _post_slack_summary(webhook, to_slack):
        # Only count as sent on a 2xx — a 4xx/5xx webhook must not inflate the stat.
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
