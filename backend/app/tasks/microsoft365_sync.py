"""Background loop that syncs every active M365 connection.

Same shape as `app/tasks/triggers_loop.py`:
- Grace period at startup so the rest of the app finishes bootstrap.
- Infinite while True that opens fresh DB sessions per iteration.
- Per-connection failures are logged + recorded on the row; the loop never dies.
- CancelledError propagates so lifespan shutdown works cleanly.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.encryption import TokenCipherNotConfigured
from app.models.m365 import (
    Email,
    EmailMatchMethod,
    GraphSubscription,
    M365Connection,
    M365SyncStatus,
)
from app.services.m365 import sync_connection
from app.services.m365 import matcher as matcher_mod
from app.services.m365 import webhooks as m365_webhooks
from app.services.m365.graph_client import GraphClient
from app.services.m365.matcher import IncomingMessage

logger = logging.getLogger(__name__)

# Fatal-error markers → skip that connection until user manually reconnects.
# These indicate the sync path itself is broken (not transient Graph flakes).
_FATAL_ERROR_MARKERS = ("timeout", "retry_after cap", "M365ReauthRequired")
# Backoff for connections whose last attempt errored — don't hammer them
# every 5 min. Artur can force with POST /api/microsoft365/sync/trigger.
_ERROR_BACKOFF_SECONDS = 30 * 60  # 30 min


async def microsoft365_sync_loop() -> None:
    """Long-running task — iterates active connections on a schedule."""
    if not settings.M365_INTEGRATION_ENABLED:
        logger.info("m365 sync loop disabled by M365_INTEGRATION_ENABLED=false")
        return
    if not settings.M365_SYNC_LOOP_ENABLED:
        logger.info(
            "m365 sync loop off (M365_SYNC_LOOP_ENABLED=false). "
            "Router still registered — enable env var to resume background sync."
        )
        return

    interval = max(60, settings.M365_SYNC_INTERVAL_SECONDS)
    logger.info("microsoft365_sync_loop started: interval=%ds", interval)
    # Give the rest of the app a head start.
    await asyncio.sleep(45)

    while True:
        try:
            await _tick(interval)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("microsoft365_sync_loop iteration failed")
        await asyncio.sleep(interval)


async def _tick(interval: int) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=interval)
    error_cutoff = now - timedelta(seconds=_ERROR_BACKOFF_SECONDS)
    async with AsyncSessionLocal() as db:
        # Pick connections where:
        #  - is_active=True
        #  - status is NOT 'error', OR the error is older than 30 min (backoff)
        #  - last_sync_at is NULL or older than the loop interval
        stmt = (
            select(M365Connection)
            .where(
                M365Connection.is_active.is_(True),
                or_(
                    M365Connection.last_sync_status != M365SyncStatus.error,
                    and_(
                        M365Connection.last_sync_status == M365SyncStatus.error,
                        M365Connection.last_sync_at < error_cutoff,
                    ),
                ),
                or_(
                    M365Connection.last_sync_at.is_(None),
                    M365Connection.last_sync_at < cutoff,
                ),
            )
            .order_by(M365Connection.last_sync_at.asc().nulls_first())
        )
        result = await db.execute(stmt)
        connections = list(result.scalars().all())
        # Skip connections whose last_error looks fatal — user must reconnect.
        connections = [
            c
            for c in connections
            if not (
                c.last_error and any(m in c.last_error for m in _FATAL_ERROR_MARKERS)
            )
        ]

    if not connections:
        return

    logger.info("m365 sync tick — %d connection(s) due", len(connections))
    for conn_id in [c.id for c in connections]:
        # Fresh session per connection so one failure doesn't poison subsequent ones.
        try:
            async with AsyncSessionLocal() as db:
                fresh = await db.get(M365Connection, conn_id)
                if fresh is None or not fresh.is_active:
                    continue
                await sync_connection(db, fresh)
        except asyncio.CancelledError:
            raise
        except TokenCipherNotConfigured:
            # Cipher key rotated or token row was encrypted with a different
            # key (most often: key was missing at first encrypt, then provisioned;
            # or rotated without re-running OAuth). Token is unrecoverable —
            # deactivate so the loop stops retrying every 300s and Sentry doesn't
            # get a flood of identical events. User must reconnect via UI to
            # set is_active=True again with a freshly encrypted token.
            async with AsyncSessionLocal() as db:
                fresh = await db.get(M365Connection, conn_id)
                if fresh is not None:
                    fresh.is_active = False
                    fresh.last_sync_status = M365SyncStatus.error
                    fresh.last_error = "token_cipher_unreadable_user_must_reconnect"
                    await db.commit()
            logger.warning(
                "m365 connection id=%s deactivated — token unreadable (cipher mismatch). "
                "User must reconnect via /microsoft365 in the UI.",
                conn_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("sync_connection failed for id=%s", conn_id)
        # Stagger calls so Graph rate limits don't kick in.
        await asyncio.sleep(2)


# ── Phase 5.2 — backfill candidate matcher (rematch unlinked emails) ──────────
#
# Why a separate loop? `matcher.match()` runs once at sync time. If a recruiter
# adds a candidate AFTER their emails are already in our DB, those emails stay
# `candidate_id=NULL, match_method=unmatched` forever. This loop retries the
# matcher hourly over the last N days so retroactive linking happens without
# the recruiter having to click around.
#
# Manual decisions are sacred:
#   - `match_method=manual` rows are already linked (skipped by NULL filter).
#   - We never touch a row that someone manually re-linked — only rows still
#     in the `unmatched` state.


@dataclass(frozen=True)
class RematchStats:
    """Per-pass counters — also handy for tests."""

    processed: int = 0
    matched: int = 0


async def rematch_unlinked_emails_loop() -> None:
    """Long-running task — retries the matcher against unlinked recent emails.

    Off by default. Set `M365_REMATCH_ENABLED=true` in Coolify env to enable.
    """
    if not settings.M365_INTEGRATION_ENABLED:
        logger.info("m365 rematch loop disabled by M365_INTEGRATION_ENABLED=false")
        return
    if not settings.M365_REMATCH_ENABLED:
        logger.info(
            "m365 rematch loop off (M365_REMATCH_ENABLED=false). "
            "Flip the env var to retroactively link emails synced before the "
            "candidate was added."
        )
        return

    interval = max(600, settings.M365_REMATCH_INTERVAL_SECONDS)
    logger.info("rematch_unlinked_emails_loop started: interval=%ds", interval)
    # Generous grace period — this is a catch-up job, the sync loop's 45s head
    # start needs to finish before we start scanning the emails table.
    await asyncio.sleep(120)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                stats = await _rematch_pass(db)
            logger.info(
                "rematch pass: processed=%d matched=%d",
                stats.processed,
                stats.matched,
            )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("rematch loop iteration failed")
        await asyncio.sleep(interval)


async def _rematch_pass(db: AsyncSession) -> RematchStats:
    """One pass: scan unlinked emails in the look-back window, try matcher.

    Pure helper — separated from the loop so tests can drive it directly.
    Returns counters for logging + assertions.
    """
    lookback_days = max(1, settings.M365_REMATCH_LOOKBACK_DAYS)
    batch_size = max(1, settings.M365_REMATCH_BATCH_SIZE)
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    stmt = (
        select(Email)
        .where(
            Email.candidate_id.is_(None),
            Email.match_method == EmailMatchMethod.unmatched,
            Email.received_at > cutoff,
        )
        .order_by(Email.received_at.desc())
        .limit(batch_size)
    )
    result = await db.execute(stmt)
    candidates_to_try = list(result.scalars().all())

    processed = 0
    matched = 0
    for email in candidates_to_try:
        processed += 1
        dto = IncomingMessage(
            from_address=email.from_address or "",
            to_addresses=_addresses(email.to_addresses),
            cc_addresses=_addresses(email.cc_addresses),
            subject=email.subject,
            conversation_id=email.m365_conversation_id,
        )
        try:
            m = await matcher_mod.match(db, dto)
        except Exception:  # noqa: BLE001
            logger.exception("matcher.match failed for email id=%s", email.id)
            continue

        if m.candidate_id is None:
            # Still unmatched — leave row as-is. No write = no churn.
            continue

        try:
            method_enum = EmailMatchMethod(m.method)
        except ValueError:
            # Defensive: matcher returned an unknown method string. Skip the
            # row rather than corrupt the enum column or leave it half-updated.
            logger.warning(
                "matcher returned unknown method=%r for email id=%s — skipping",
                m.method,
                email.id,
            )
            continue
        email.candidate_id = m.candidate_id
        email.match_method = method_enum
        email.match_confidence = m.confidence
        email.matched_at = datetime.now(timezone.utc)
        matched += 1

    if matched:
        await db.commit()

    return RematchStats(processed=processed, matched=matched)


def _addresses(raw: object) -> list[str]:
    """Extract `address` keys from the JSONB `to_addresses` / `cc_addresses` shape.

    Email columns store `[{"address": str, "name": str?}, ...]`. We feed only
    the address strings into IncomingMessage.
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for entry in raw:
        if isinstance(entry, dict):
            addr = entry.get("address")
            if isinstance(addr, str) and addr:
                out.append(addr)
    return out


# ── Phase 7.3 — Graph push-subscription renewal ─────────────────────────────
#
# Microsoft Graph caps a subscription's lifetime, so without a renewal loop
# the push pipeline silently stops working after ~70h. This loop:
#   - Renews rows whose expires_at falls inside the renewal window.
#   - Re-enrols missing (resource, change_type) combos for active connections
#     so a 3-strike failure on one subscription self-heals next pass.
#
# Why a separate loop (and not piggybacking on microsoft365_sync_loop): renewal
# cadence (~10 min) is much faster than the future "webhooks only" sync, and
# the polling loop will be turned off entirely once we're confident in pushes.


async def graph_subscription_renewal_loop() -> None:
    """Long-running task — keeps Graph push subscriptions alive.

    Off by default. Flip `M365_WEBHOOKS_ENABLED=true` in Coolify env to enable.
    Loop never dies on per-iteration failures (same pattern as the sync loop).
    """
    if not settings.M365_INTEGRATION_ENABLED:
        logger.info(
            "graph_subscription_renewal_loop disabled by M365_INTEGRATION_ENABLED=false"
        )
        return
    if not settings.M365_WEBHOOKS_ENABLED:
        logger.info(
            "graph_subscription_renewal_loop off (M365_WEBHOOKS_ENABLED=false). "
            "Endpoint stays registered for validation handshakes."
        )
        return

    interval = max(60, settings.M365_WEBHOOK_RENEWAL_INTERVAL_SECONDS)
    logger.info("graph_subscription_renewal_loop started: interval=%ds", interval)
    # Generous head start — let OAuth callback's auto_subscribe (which runs in
    # its own task on user connect) commit rows before we look for stale ones.
    await asyncio.sleep(60)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                await _renewal_tick(db)
                await _backfill_missing_subscriptions(db)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("graph_subscription_renewal_loop iteration failed")
        await asyncio.sleep(interval)


async def _renewal_tick(db: AsyncSession) -> None:
    """Renew any subscriptions whose expires_at is inside the window."""
    due = await m365_webhooks.list_due_for_renewal(db)
    if not due:
        return

    # Group by connection so we open ONE GraphClient per connection (each open
    # does an OAuth token decrypt + HTTP client setup).
    by_conn: dict[int, list[GraphSubscription]] = {}
    for sub in due:
        by_conn.setdefault(sub.m365_connection_id, []).append(sub)

    logger.info(
        "renewal tick — %d subscription(s) across %d connection(s) due",
        len(due),
        len(by_conn),
    )

    for conn_id, subs in by_conn.items():
        conn = await db.get(M365Connection, conn_id)
        if conn is None or not conn.is_active:
            # Orphan / soft-deleted — drop rows so we don't keep selecting them.
            for sub in subs:
                await db.delete(sub)
            await db.commit()
            continue

        try:
            async with GraphClient(conn, db) as gc:
                for sub in subs:
                    try:
                        await m365_webhooks.renew(db, gc, sub)
                    except asyncio.CancelledError:
                        raise
                    except Exception:  # noqa: BLE001
                        logger.exception(
                            "renew failed for sub id=%s — left for next tick",
                            sub.id,
                        )
            await db.commit()
        except TokenCipherNotConfigured:
            # Token is unrecoverable — sync loop already handles this for the
            # connection; we just skip the subs to avoid Sentry flood.
            logger.warning("renewal skip: conn=%s token undecryptable", conn_id)
        except Exception:  # noqa: BLE001
            logger.exception("renewal_tick: connection %s failed", conn_id)
        # Brief stagger so Graph rate limits don't kick in across many users.
        await asyncio.sleep(1)


async def _backfill_missing_subscriptions(db: AsyncSession) -> None:
    """Re-enrol resources that have no live row for an active connection.

    Triggered when a previous tick deleted a row after the failure threshold,
    or when an admin manually deleted rows. Iterates active connections and
    subscribes any resource from DEFAULT_RESOURCES that isn't already tracked.
    """
    # Pull every active connection that has at least one missing default
    # resource. Cheap because the table is tiny (one row per connected user).
    conns_result = await db.execute(
        select(M365Connection).where(M365Connection.is_active.is_(True))
    )
    connections = list(conns_result.scalars().all())
    if not connections:
        return

    for conn in connections:
        existing_result = await db.execute(
            select(GraphSubscription.resource).where(
                GraphSubscription.m365_connection_id == conn.id
            )
        )
        existing_resources = {r for (r,) in existing_result.all()}
        missing = [
            (resource, change_type)
            for (resource, change_type) in m365_webhooks.DEFAULT_RESOURCES
            if resource not in existing_resources
        ]
        if not missing:
            continue

        logger.info(
            "backfill subscriptions for conn=%s missing=%d",
            conn.id,
            len(missing),
        )
        try:
            await m365_webhooks.subscribe_all_for_connection(
                db, conn, resources=missing
            )
            await db.commit()
        except Exception:  # noqa: BLE001
            logger.exception("backfill subscriptions failed for conn=%s", conn.id)
