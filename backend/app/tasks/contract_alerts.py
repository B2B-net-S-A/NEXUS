"""Phase 9 A5 — contract status transitions + ending alerts.

Runs once a day. Responsibilities:
    1. Promote active → ending when end_date - today ≤ 30.
    2. Promote ending → ended when end_date < today.
    3. For each active/ending contract with end_date at T-60/30/14/7 days,
       create in-app Notification rows for active admins and authorised,
       client-assigned Delivery Leads, then post one summary message to Slack
       (if SLACK_WEBHOOK_URL set).
    4. Dedup: Notification rows are keyed by (user, contract, threshold_days).
       We never re-notify for the same triple.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import timedelta
from typing import Iterable

import httpx
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.contract import Contract, ContractStatus
from app.models.contract_alert_dedup import ContractAlertDedup
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.contract_equipment import ContractEquipment, EquipmentReturnStatus
from app.models.notification import Notification, NotificationType
from app.services.contract_order_offboarding import (
    apply_contract_order_offboarding,
    reconcile_pending_md_offboarding_alerts,
)
from app.services.delivery_alert_recipients import (
    load_delivery_alert_recipient_scope,
)

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


async def _promote_statuses(db: AsyncSession) -> tuple[int, int]:
    """Move active→ending and ending→ended based on end_date.

    `business_today()`, nie `date.today()`: kontener chodzi w UTC (Dockerfile
    nie ustawia TZ), więc między północą warszawską a północą UTC — 2 h latem,
    1 h zimą — `date.today()` zwraca WCZORAJ. Kontrakt kończący się dziś
    zostawałby wtedy `active` jeszcze przez dobę, a alert liczyłby o dzień
    więcej niż widzi odbiorca. Objaw jest cichy: liczba jest poprawna, tylko
    opisuje inny dzień.
    """
    today = business_today()
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
    ended_contracts = list(
        (
            await db.execute(
                select(Contract)
                .where(
                    Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
                    Contract.end_date.isnot(None),
                    Contract.end_date < today,
                )
                .order_by(Contract.id.asc())
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for contract in ended_contracts:
        contract.status = ContractStatus.ended
        await apply_contract_order_offboarding(
            db,
            contract_id=contract.id,
            effective_date=contract.end_date,
            actor_id=None,
            today=today,
        )
    return (ending_count.rowcount or 0, len(ended_contracts))


async def _client_ids_by_contract_id(
    db: AsyncSession, contract_ids: Iterable[int]
) -> dict[int, int]:
    """Resolve contract ownership once for client-scoped notification fan-out."""

    ids = sorted(set(contract_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(Contract.id, Contract.client_id).where(Contract.id.in_(ids))
    )
    return {contract_id: client_id for contract_id, client_id in rows.all()}


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
    """Pull the episode discriminator encoded as ``[tag|<value>]`` from an alert title.

    Shared by every episode-aware family (F-29): ending ``[Nd|<end_date>]``, compliance
    ``[compliance|<expiry>]``, equipment ``[eq_ret|<due>]``, client order
    ``[client_order|<order_end>]``. Returns ``None`` for legacy ``[tag]`` titles that
    carry no discriminator — those never match an episode, so an entity still inside a
    window at ship time may re-alert once (an acceptable one-off, not a silent gap).
    """
    if not title or not title.startswith("["):
        return None
    close = title.find("]")
    if close == -1:
        return None
    _, sep, episode = title[1:close].partition("|")  # "30d|2026-09-01" -> "2026-09-01"
    if not sep:
        return None
    return episode.strip() or None


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
    today = business_today()
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
    today = business_today()
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


async def _compliance_already_notified(db: AsyncSession) -> set[tuple[int, str]]:
    """Return ``(doc_id, expiry_iso)`` compliance episodes already reported.

    Episode-aware dedup (F-29): the title encodes the document's current expiry as
    ``[compliance|<expiry>]``, so a renewed document with a fresh ``expiry_date`` is a
    NEW episode — the pair no longer matches and the alert re-arms. A document counts
    as already-notified ONLY when a prior notification exists for the SAME expiry. The
    ``[compliance%`` prefix also catches legacy ``[compliance]`` rows; those parse to a
    ``None`` expiry and drop out (a doc still in-window at ship time may re-alert once).
    """
    res = await db.execute(
        select(Notification.message, Notification.title).where(
            Notification.notification_type == NotificationType.contract_ending,
            Notification.title.like("[compliance%"),
        )
    )
    episodes: set[tuple[int, str]] = set()
    for msg, title in res.all():
        expiry_iso = _end_date_from_title(title)
        if expiry_iso is None or not msg:
            continue
        # Message encodes the doc id as '(doc_id=<N>)'; match anywhere so the
        # surrounding parens do not defeat the parse.
        m = re.search(r"doc_id=(\d+)", msg)
        if m:
            episodes.add((int(m.group(1)), expiry_iso))
    return episodes


async def _equipment_due_for_return(db: AsyncSession) -> list[ContractEquipment]:
    today = business_today()
    cutoff = today + timedelta(days=EQUIPMENT_RETURN_THRESHOLD_DAYS)
    res = await db.execute(
        select(ContractEquipment).where(
            ContractEquipment.return_status == EquipmentReturnStatus.pending,
            ContractEquipment.return_due_date.isnot(None),
            ContractEquipment.return_due_date <= cutoff,
        )
    )
    return list(res.scalars().all())


async def _equipment_already_notified(db: AsyncSession) -> set[tuple[int, str]]:
    """Return ``(equipment_id, due_iso)`` return episodes already reported.

    Episode-aware dedup (F-29): the title encodes the current ``return_due_date`` as
    ``[eq_ret|<due>]``, so a piece of equipment re-flagged ``pending`` with a fresh due
    date is a NEW episode and re-arms — the old, id-only key permanently suppressed it.
    Legacy ``[eq_ret]`` rows carry no due date and drop out (may re-alert once).
    """
    res = await db.execute(
        select(Notification.related_entity_id, Notification.title).where(
            Notification.notification_type == NotificationType.equipment_return_due_14d,
            Notification.related_entity_type == "contract_equipment",
        )
    )
    episodes: set[tuple[int, str]] = set()
    for entity_id, title in res.all():
        due_iso = _end_date_from_title(title)
        if entity_id is None or due_iso is None:
            continue
        episodes.add((entity_id, due_iso))
    return episodes


async def _client_orders_ending(db: AsyncSession) -> list[Contract]:
    today = business_today()
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


async def _client_order_already_notified(db: AsyncSession) -> set[tuple[int, str]]:
    """Return ``(contract_id, order_end_iso)`` client-order episodes already reported.

    Episode-aware dedup (F-29): the title encodes the current ``client_order_end_date``
    as ``[client_order|<order_end>]``, so a client order extended to a fresh end date is
    a NEW episode and re-arms — the old, id-only key permanently suppressed it. Legacy
    ``[client_order]`` rows carry no date and drop out (may re-alert once).
    """
    res = await db.execute(
        select(Notification.related_entity_id, Notification.title).where(
            Notification.notification_type == NotificationType.client_order_ending_30d,
            Notification.related_entity_type == "contract",
        )
    )
    episodes: set[tuple[int, str]] = set()
    for entity_id, title in res.all():
        order_iso = _end_date_from_title(title)
        if entity_id is None or order_iso is None:
            continue
        episodes.add((entity_id, order_iso))
    return episodes


async def run_contract_alerts_cycle() -> dict:
    """One pass: promote statuses + create notifications + post Slack summary."""
    stats = {
        "promoted_ending": 0,
        "promoted_ended": 0,
        "notifications_created": 0,
        "compliance_alerts": 0,
        "equipment_return_alerts": 0,
        "client_order_alerts": 0,
        "md_offboarding_alerts": 0,
        "slack_sent": 0,
    }
    async with AsyncSessionLocal() as db:
        ending, ended = await _promote_statuses(db)
        stats["promoted_ending"] = ending
        stats["promoted_ended"] = ended
        stats["md_offboarding_alerts"] = await reconcile_pending_md_offboarding_alerts(
            db
        )
        await db.commit()

        recipient_scope = await load_delivery_alert_recipient_scope(db)
        if recipient_scope.is_empty:
            logger.info(
                "contract_alerts: no authorised Delivery recipients — "
                "skipping notifications"
            )
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
                recipient_ids = recipient_scope.for_client(c.client_id)
                if not recipient_ids:
                    continue
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
                for uid in recipient_ids:
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
        if not recipient_scope.is_empty:
            expiring = await _compliance_documents_expiring(db)
            client_ids = await _client_ids_by_contract_id(
                db, (doc.contract_id for doc in expiring)
            )
            already = await _compliance_already_notified(db)
            # Episode-aware: a renewed document re-alerts once its CURRENT expiry forms
            # a new (id, expiry) pair. ``_compliance_documents_expiring`` guarantees a
            # non-null expiry_date, so the isoformat() is always available.
            fresh = [
                d
                for d in expiring
                if d.expiry_date is not None
                and (d.id, d.expiry_date.isoformat()) not in already
            ]
            for doc in fresh:
                recipient_ids = recipient_scope.for_client(
                    client_ids.get(doc.contract_id)
                )
                if not recipient_ids:
                    continue
                episode = doc.expiry_date.isoformat()
                # Claim key carries the expiry too, so the atomic ledger re-arms on
                # renewal just like the SELECT pre-filter above.
                if not await _claim_alert(db, f"compliance:{doc.id}:{episode}"):
                    continue
                title = f"[compliance|{episode}] Dokument #{doc.id} wygasa"
                message = (
                    f"Dokument {doc.doc_type.value} (doc_id={doc.id}) kontraktu "
                    f"#{doc.contract_id} wygasa {doc.expiry_date}. "
                    f"Zamów nowy zanim straci ważność."
                )
                for uid in recipient_ids:
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
        if not recipient_scope.is_empty:
            due = await _equipment_due_for_return(db)
            client_ids = await _client_ids_by_contract_id(
                db, (item.contract_id for item in due)
            )
            already = await _equipment_already_notified(db)
            # Episode-aware: equipment re-flagged pending with a fresh return_due_date
            # forms a new (id, due) pair and re-arms. ``_equipment_due_for_return``
            # guarantees a non-null return_due_date.
            fresh = [
                item
                for item in due
                if item.return_due_date is not None
                and (item.id, item.return_due_date.isoformat()) not in already
            ]
            for item in fresh:
                recipient_ids = recipient_scope.for_client(
                    client_ids.get(item.contract_id)
                )
                if not recipient_ids:
                    continue
                episode = item.return_due_date.isoformat()
                # Claim key carries the due date too, so the atomic ledger re-arms on a
                # new due date just like the SELECT pre-filter above.
                if not await _claim_alert(db, f"equipment:{item.id}:{episode}"):
                    continue
                days_left = (item.return_due_date - business_today()).days
                title = f"[eq_ret|{episode}] Sprzęt do zwrotu — item #{item.id}"
                message = (
                    f"Sprzęt {item.item_type.value} "
                    f"(serial={item.serial_number or '—'}) z kontraktu "
                    f"#{item.contract_id} ma być zwrócony "
                    f"{item.return_due_date} ({days_left} dni)."
                )
                for uid in recipient_ids:
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
        if not recipient_scope.is_empty:
            orders = await _client_orders_ending(db)
            already = await _client_order_already_notified(db)
            # Episode-aware: a client order extended to a fresh client_order_end_date
            # forms a new (id, order_end) pair and re-arms. ``_client_orders_ending``
            # guarantees a non-null client_order_end_date.
            fresh = [
                c
                for c in orders
                if c.client_order_end_date is not None
                and (c.id, c.client_order_end_date.isoformat()) not in already
            ]
            for c in fresh:
                recipient_ids = recipient_scope.for_client(c.client_id)
                if not recipient_ids:
                    continue
                episode = c.client_order_end_date.isoformat()
                # Claim key carries the order end date too, so the atomic ledger re-arms
                # on an extended order just like the SELECT pre-filter above.
                if not await _claim_alert(db, f"client_order:{c.id}:{episode}"):
                    continue
                days_left = (c.client_order_end_date - business_today()).days
                title = (
                    f"[client_order|{episode}] Kontrakt #{c.id} — "
                    f"zamówienie klienta kończy się"
                )
                message = (
                    f"Zamówienie klienta dla kontraktu #{c.id} wygasa "
                    f"{c.client_order_end_date} ({days_left} dni). "
                    f"Skontaktuj się z klientem w sprawie przedłużenia."
                )
                for uid in recipient_ids:
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
        except Exception:  # noqa: BLE001
            # `exception`, nie `warning`: Sentry ma `event_level=logging.ERROR`
            # (`main.py:271`), więc na WARNING trwale padający cykl nie wygenerowałby
            # żadnego zdarzenia — pętla kręciłaby się w kółko, a alerty o kończących
            # się umowach po prostu by nie przychodziły, bez śladu poza logiem kontenera.
            logger.exception("contract_alerts: cycle error")
        await asyncio.sleep(interval_hours * 3600)


def thresholds() -> Iterable[int]:
    """Exported for tests."""
    return THRESHOLDS_DAYS
