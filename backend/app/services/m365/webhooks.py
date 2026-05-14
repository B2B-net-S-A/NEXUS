"""Microsoft Graph push-webhook subscription helpers.

Phase 7.3 — replaces (eventually) the 5-min polling loop with real-time
notifications. Microsoft Graph caps a single subscription's lifetime, so this
module owns the full lifecycle: subscribe → store → renew before expiry →
unsubscribe on disconnect.

Why this exists as a service module (and not inside the loop):
- The OAuth callback wants to enrol a brand-new connection immediately.
- The renewal loop wants to PATCH rows that are about to expire.
- Tests want to exercise each verb without spinning up the loop.

Reference: https://learn.microsoft.com/en-us/graph/webhooks
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.m365 import GraphSubscription, M365Connection
from app.services.m365.graph_client import GraphClient, GraphRequestError

logger = logging.getLogger(__name__)


# Resources we subscribe to. Order matters only for log clarity. Tuples are
# `(resource_path, change_type)`. We split inbox vs sentitems explicitly
# because each Outlook folder needs its own subscription — Graph does not
# accept a wildcard "all folders" resource for mail.
DEFAULT_RESOURCES: tuple[tuple[str, str], ...] = (
    ("me/mailFolders('inbox')/messages", "created,updated"),
    ("me/mailFolders('sentitems')/messages", "created,updated"),
    ("me/events", "created,updated,deleted"),
)


def _notification_url() -> str:
    """Public endpoint Graph will POST notifications to.

    Graph requires HTTPS; we don't validate that here because production envs
    enforce it via the deploy-time setting and tests stub the call entirely.
    """
    base = settings.M365_WEBHOOK_BASE_URL.rstrip("/")
    return f"{base}/api/microsoft365/webhooks"


def _expiration_iso(minutes: int | None = None) -> str:
    """ISO 8601 expiry that Graph expects (UTC, no fractional seconds)."""
    minutes = minutes or settings.M365_WEBHOOK_LIFETIME_MINUTES
    when = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    # Graph rejects fractional seconds — strip microseconds and use 'Z'.
    return when.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_graph_iso(value: str) -> datetime:
    """Parse Graph's expirationDateTime (always ends with 'Z')."""
    # Replace trailing Z with +00:00 so fromisoformat understands it on 3.10.
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


async def subscribe(
    db: AsyncSession,
    gc: GraphClient,
    conn: M365Connection,
    resource: str,
    change_type: str,
) -> GraphSubscription:
    """Create one Graph subscription and persist its tracking row.

    The caller owns the AsyncSession and transaction boundary — we add and
    flush, never commit. This lets the OAuth callback enrol three resources
    in a single commit.
    """
    client_state = secrets.token_urlsafe(32)
    notification_url = _notification_url()
    body = {
        "changeType": change_type,
        "notificationUrl": notification_url,
        "resource": resource,
        "expirationDateTime": _expiration_iso(),
        "clientState": client_state,
    }

    response = await gc.post("/subscriptions", json=body)
    if not isinstance(response, dict) or "id" not in response:
        raise GraphRequestError(
            response.get("error", {}).get("code", 502)
            if isinstance(response, dict)
            else 502,
            f"Graph subscription create returned unexpected body: {response!r}",
        )

    expires_at = _parse_graph_iso(response["expirationDateTime"])
    row = GraphSubscription(
        user_id=conn.user_id,
        m365_connection_id=conn.id,
        resource=resource,
        change_type=change_type,
        subscription_id=response["id"],
        notification_url=notification_url,
        client_state=client_state,
        expires_at=expires_at,
        renewal_failure_count=0,
    )
    db.add(row)
    await db.flush()
    logger.info(
        "graph_subscription created: id=%s sub_id=%s resource=%s expires=%s",
        row.id,
        row.subscription_id,
        resource,
        expires_at.isoformat(),
    )
    return row


async def subscribe_all_for_connection(
    db: AsyncSession,
    conn: M365Connection,
    resources: Iterable[tuple[str, str]] = DEFAULT_RESOURCES,
) -> list[GraphSubscription]:
    """Enrol Inbox + SentItems + Events subscriptions for one connection.

    Best-effort: per-resource failures are logged but do not abort the others.
    Returns the rows that succeeded. Used from the OAuth callback so a single
    transient Graph 5xx on one resource doesn't block the whole connect.
    """
    rows: list[GraphSubscription] = []
    async with GraphClient(conn, db) as gc:
        for resource, change_type in resources:
            try:
                row = await subscribe(db, gc, conn, resource, change_type)
                rows.append(row)
            except Exception:  # noqa: BLE001
                # Renewal loop will retry on the next pass via re-enrolment of
                # expired-without-row resources. Surface to Sentry via logger.exception.
                logger.exception(
                    "subscribe failed for conn=%s resource=%s — will retry from loop",
                    conn.id,
                    resource,
                )
    return rows


async def renew(
    db: AsyncSession,
    gc: GraphClient,
    sub: GraphSubscription,
) -> bool:
    """Extend a subscription's lifetime via PATCH /subscriptions/{id}.

    Returns True on success. On failure: bumps `renewal_failure_count`,
    records `last_error`, and (if past threshold) deletes the row so the
    next loop iteration triggers a fresh `subscribe()`.
    """
    new_expiry = _expiration_iso()
    try:
        response = await gc.patch(
            f"/subscriptions/{sub.subscription_id}",
            json={"expirationDateTime": new_expiry},
        )
    except GraphRequestError as exc:
        sub.renewal_failure_count += 1
        sub.last_error = f"renew failed: {exc!r}"[:2000]
        if sub.renewal_failure_count >= settings.M365_WEBHOOK_FAILURE_THRESHOLD:
            # Graph likely revoked it (404 on subsequent calls is common).
            # Drop the row; next renewal pass re-subscribes from scratch.
            logger.warning(
                "graph_subscription %s exceeded failure threshold — deleting row",
                sub.id,
            )
            await db.delete(sub)
        return False

    if isinstance(response, dict) and "expirationDateTime" in response:
        sub.expires_at = _parse_graph_iso(response["expirationDateTime"])
    else:
        # Graph occasionally returns 200 with no body on PATCH — fall back to
        # our requested time, which is a safe lower bound.
        sub.expires_at = _parse_graph_iso(new_expiry)
    sub.last_renewed_at = datetime.now(timezone.utc)
    sub.renewal_failure_count = 0
    sub.last_error = None
    logger.info(
        "graph_subscription renewed: id=%s new_expires=%s",
        sub.id,
        sub.expires_at.isoformat(),
    )
    return True


async def unsubscribe(
    db: AsyncSession,
    gc: GraphClient,
    sub: GraphSubscription,
) -> None:
    """DELETE /subscriptions/{id} then drop the row.

    Best-effort on the Graph side — 404 is fine (subscription already gone)
    and any other error still removes our row so we don't try to renew a
    subscription Graph has lost track of.
    """
    try:
        await gc.delete(f"/subscriptions/{sub.subscription_id}")
    except GraphRequestError as exc:
        if exc.status not in (404, 410):
            logger.warning(
                "graph_subscription unsubscribe failed (status=%s) — dropping row anyway",
                exc.status,
            )
    await db.delete(sub)
    await db.flush()


async def unsubscribe_all_for_connection(
    db: AsyncSession, conn: M365Connection
) -> None:
    """Tear down every subscription for a connection (called on disconnect)."""
    stmt = select(GraphSubscription).where(
        GraphSubscription.m365_connection_id == conn.id
    )
    rows = list((await db.execute(stmt)).scalars().all())
    if not rows:
        return
    async with GraphClient(conn, db) as gc:
        for row in rows:
            try:
                await unsubscribe(db, gc, row)
            except Exception:  # noqa: BLE001
                logger.exception("unsubscribe_all: row id=%s failed — skipping", row.id)


async def auto_subscribe_after_connect(connection_id: int) -> None:
    """Fire-and-forget — enrol push subscriptions for a freshly connected mailbox.

    Called from the OAuth callback as `asyncio.create_task(...)` so the user-
    facing redirect is not delayed by Graph POSTs. Owns its own AsyncSession.
    No-op when the feature flag is off so callers can fire unconditionally.
    """
    if not settings.M365_WEBHOOKS_ENABLED:
        return
    async with AsyncSessionLocal() as db:
        conn = await db.get(M365Connection, connection_id)
        if conn is None or not conn.is_active:
            return
        try:
            await subscribe_all_for_connection(db, conn)
            await db.commit()
        except Exception:  # noqa: BLE001
            # The renewal loop is the safety net — if every subscribe failed
            # the loop will retry on its next pass (which re-enrols missing
            # resources for active connections).
            logger.exception(
                "auto_subscribe_after_connect failed for connection_id=%s",
                connection_id,
            )


async def list_due_for_renewal(
    db: AsyncSession, window_minutes: int | None = None
) -> list[GraphSubscription]:
    """Rows whose expires_at falls inside the renewal window (or already past).

    The renewal loop iterates this list once per tick. We pull the M365
    connection along for the ride so callers don't N+1 the FK fetch.
    """
    window = window_minutes or settings.M365_WEBHOOK_RENEWAL_WINDOW_MINUTES
    cutoff = datetime.now(timezone.utc) + timedelta(minutes=window)
    stmt = (
        select(GraphSubscription)
        .where(GraphSubscription.expires_at <= cutoff)
        .order_by(GraphSubscription.expires_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())
