"""Per-connection sync orchestrator.

Called by `backend/app/tasks/microsoft365_sync.py` every `M365_SYNC_INTERVAL_SECONDS`,
and by `/api/microsoft365/callback` as an asyncio task for the initial backfill.

Strategy:
- Messages: delta query over `/me/mailFolders/Inbox/messages` + `/SentItems`.
  First run (no delta token) = backfill with `$filter=receivedDateTime ge <12mo>`.
- Events: delta query over `/me/calendarView/delta?startDateTime=..&endDateTime=..`.
- Both persist their `@odata.deltaLink` for the next iteration.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Hard ceiling on a single sync pass — guards against a hung Graph call
# holding the DB connection and poisoning the pool.
_SYNC_TIMEOUT_SECONDS = 8 * 60

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.encryption import TokenCipherNotConfigured
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.m365 import (
    Email,
    EmailDirection,
    EmailMatchMethod,
    M365Connection,
    M365SyncStatus,
)
from app.services.m365 import attachment_handler, matcher
from app.services.m365.access import connection_owner_is_eligible
from app.services.m365.calendar import M365_SOURCE
from app.services.m365.graph_client import GraphClient, GraphRequestError
from app.services.m365.html_sanitize import html_to_text, sanitize_html
from app.services.m365.matcher import IncomingMessage
from app.services.candidate_contact_hooks import maybe_remove_calendar_handoff

logger = logging.getLogger(__name__)

MESSAGE_SELECT = (
    "id,conversationId,internetMessageId,subject,from,toRecipients,ccRecipients,"
    "sentDateTime,receivedDateTime,bodyPreview,body,hasAttachments,isRead,"
    "categories,parentFolderId"
)
EVENT_SELECT = (
    "id,changeKey,subject,bodyPreview,body,start,end,"
    "organizer,attendees,location,seriesMasterId,type,isCancelled"
)


@dataclass
class SyncResult:
    connection_id: int
    messages_ingested: int = 0
    attachments_downloaded: int = 0
    events_ingested: int = 0
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)


# ── Entry point ─────────────────────────────────────────────────────────────


async def sync_connection(db: AsyncSession, conn: M365Connection) -> SyncResult:
    """Run one full sync pass (messages + events) for the given connection.

    - Hard timeout (`_SYNC_TIMEOUT_SECONDS`) so a hung Graph call can't hold the
      DB connection open indefinitely.
    - `last_sync_at` is set on BOTH success and error so the scheduler's cutoff
      test behaves correctly (otherwise a failing row keeps being picked up
      every loop iteration).
    """
    result = SyncResult(connection_id=conn.id)
    if not await connection_owner_is_eligible(db, conn):
        logger.warning(
            "m365 sync refused for ineligible connection owner: connection_id=%s",
            conn.id,
        )
        return result

    conn.last_sync_status = M365SyncStatus.running
    conn.last_error = None
    await db.commit()

    try:

        async def _run() -> None:
            async with GraphClient(conn, db) as gc:
                await _sync_messages(db, gc, conn, result)
                await _sync_events(db, gc, conn, result)

        await asyncio.wait_for(_run(), timeout=_SYNC_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        logger.warning("m365 sync_connection TIMEOUT for %s", conn.id)
        conn.last_sync_status = M365SyncStatus.error
        conn.last_error = f"timeout after {_SYNC_TIMEOUT_SECONDS}s"
        conn.last_sync_at = datetime.now(timezone.utc)
        result.errors += 1
        result.error_samples.append("top: asyncio.TimeoutError")
        await db.commit()
        return result
    except TokenCipherNotConfigured as exc:
        # Encryption key rotated or misconfigured — tokens are dead weight.
        # Mark the connection so the UI can show a "Reconnect required" banner
        # and stop generating Sentry noise every sync iteration.
        from app.services.m365.connection_status import mark_reconnect_required

        logger.warning(
            "m365 sync_connection %s: tokens undecryptable — reconnect required",
            conn.id,
        )
        await mark_reconnect_required(db, conn, f"{exc!r}"[:500])
        result.errors += 1
        result.error_samples.append("top: TokenCipherNotConfigured")
        return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("m365 sync_connection failed for %s", conn.id)
        conn.last_sync_status = M365SyncStatus.error
        conn.last_error = f"{exc!r}"[:2000]
        conn.last_sync_at = datetime.now(timezone.utc)
        result.errors += 1
        result.error_samples.append(f"top: {exc!r}")
        await db.commit()
        return result

    conn.last_sync_status = M365SyncStatus.idle
    conn.last_sync_at = datetime.now(timezone.utc)
    await db.commit()
    return result


async def trigger_backfill(connection_id: int) -> None:
    """Fire-and-forget wrapper used from the OAuth callback.

    Opens its own DB session so it survives the HTTP request that started it.
    """
    async with AsyncSessionLocal() as db:
        conn = await db.get(M365Connection, connection_id)
        if conn is None:
            logger.warning("trigger_backfill: connection %s missing", connection_id)
            return
        await sync_connection(db, conn)


# ── Messages ────────────────────────────────────────────────────────────────


async def _sync_messages(
    db: AsyncSession,
    gc: GraphClient,
    conn: M365Connection,
    result: SyncResult,
) -> None:
    """Pull messages via delta query (or initial backfill) and upsert them.

    Phase 2.5 — Inbox and SentItems use SEPARATE delta cursors so neither
    folder overwrites the other's progress. Phase 2.4 — on a 410 we bump
    `delta_reset_count`; if more than 3 within 24h the connection is
    deactivated to stop a runaway full-refetch.
    """
    # Per-folder backfill detection: a folder with NO cursor is treated as
    # "first time" and pulls `M365_BACKFILL_MONTHS` of history.
    folder_specs = [
        ("Inbox", "delta_token_inbox"),
        ("SentItems", "delta_token_sent"),
    ]

    any_backfill = False

    for folder, cursor_attr in folder_specs:
        is_backfill = getattr(conn, cursor_attr) is None
        any_backfill = any_backfill or is_backfill
        try:
            await _sync_messages_for_folder(
                db, gc, conn, result, folder, cursor_attr, is_backfill
            )
        except GraphRequestError as exc:
            if exc.status == 410:
                # Delta token invalidated. Reset to None so the next run does
                # a 30-day fallback. Increment counter; if it's a runaway,
                # deactivate to stop the cycle.
                await _on_delta_invalidation(db, conn, folder, cursor_attr)
            else:
                raise

    if any_backfill:
        # Mark backfill complete only when ALL folders have a cursor (i.e. no
        # folder is still in "first time" mode after this run).
        if conn.delta_token_inbox is not None and conn.delta_token_sent is not None:
            conn.backfill_completed_at = datetime.now(timezone.utc)
            conn.synced_through = datetime.now(timezone.utc)
            await db.commit()


# Phase 2.4 — max 410-resets within 24h before we give up.
_MAX_DELTA_RESETS_PER_24H = 3


def _is_valid_delta_link(url: Optional[str]) -> bool:
    """Sanity-check a persisted delta link before we hand it back to Graph.

    Cheap defense against accidental corruption — we don't fully parse the
    URL, just verify the shape Graph emits: HTTPS, graph.microsoft.com host,
    and a `$deltatoken=` parameter. Anything else gets treated as None and
    triggers a fresh backfill.
    """
    if not url:
        return False
    return url.startswith("https://graph.microsoft.com/") and "$deltatoken=" in url


async def _on_delta_invalidation(
    db: AsyncSession,
    conn: M365Connection,
    folder: str,
    cursor_attr: str,
) -> None:
    """Phase 2.4 — reset the cursor and decide whether to deactivate.

    A normal 410 (delta token expired after ~30 days of inactivity) is fine
    and self-heals on the next iteration. A 410 that recurs within 24h after
    we've already reset 3 times is a sign of something deeper (Graph schema
    change, broken upsert that prevents acknowledging deltas, etc.) — we
    deactivate so the loop doesn't keep re-pulling 30 days of mail forever.
    """
    now = datetime.now(timezone.utc)
    last = conn.delta_last_reset_at
    within_24h = last is not None and (now - last) < timedelta(hours=24)
    if within_24h:
        conn.delta_reset_count = (conn.delta_reset_count or 0) + 1
    else:
        # Outside window — start a fresh count of 1.
        conn.delta_reset_count = 1
    conn.delta_last_reset_at = now
    setattr(conn, cursor_attr, None)

    if conn.delta_reset_count > _MAX_DELTA_RESETS_PER_24H:
        logger.error(
            "m365 conn %s: %s delta reset %d× in 24h — deactivating",
            conn.id,
            folder,
            conn.delta_reset_count,
        )
        conn.is_active = False
        conn.last_sync_status = M365SyncStatus.error
        conn.last_error = (
            f"Delta cursor for {folder} invalidated "
            f"{conn.delta_reset_count}× in 24h — manual intervention required."
        )
    else:
        logger.warning(
            "m365 conn %s: Delta 410 for %s — reset count %d/%d in 24h window",
            conn.id,
            folder,
            conn.delta_reset_count,
            _MAX_DELTA_RESETS_PER_24H,
        )
    await db.commit()


async def _sync_messages_for_folder(
    db: AsyncSession,
    gc: GraphClient,
    conn: M365Connection,
    result: SyncResult,
    folder: str,
    cursor_attr: str,
    is_backfill: bool,
) -> None:
    """Phase 2.5 — `cursor_attr` is "delta_token_inbox" or "delta_token_sent",
    so each folder maintains its own deltaLink independently."""
    existing_cursor = getattr(conn, cursor_attr)
    if _is_valid_delta_link(existing_cursor):
        url = existing_cursor
        params = None
    else:
        if existing_cursor:
            logger.warning(
                "m365 conn %s: %s has invalid delta link — falling back to backfill",
                conn.id,
                cursor_attr,
            )
            setattr(conn, cursor_attr, None)
        url = f"/me/mailFolders/{folder}/messages/delta"
        params = {"$top": 50, "$select": MESSAGE_SELECT}
        if is_backfill:
            cutoff = datetime.now(timezone.utc) - timedelta(
                days=30 * settings.M365_BACKFILL_MONTHS
            )
            params["$filter"] = f"receivedDateTime ge {cutoff.isoformat()}"
        else:
            # 30-day fallback after invalidation.
            cutoff = datetime.now(timezone.utc) - timedelta(days=30)
            params["$filter"] = f"receivedDateTime ge {cutoff.isoformat()}"

    last_delta_link: Optional[str] = None

    async for page in gc.paginate(url, params=params):
        for msg in page.get("value", []):
            try:
                upserted = await _upsert_message(db, gc, conn, msg, folder)
                if upserted is not None:
                    result.messages_ingested += 1
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed to ingest message %s", msg.get("id"))
                result.errors += 1
                if len(result.error_samples) < 20:
                    result.error_samples.append(f"msg: {exc!r}")
        # Commit per page so long backfills don't hold one huge transaction.
        await db.commit()
        if page.get("@odata.deltaLink"):
            last_delta_link = page["@odata.deltaLink"]

    if last_delta_link and _is_valid_delta_link(last_delta_link):
        setattr(conn, cursor_attr, last_delta_link)
        await db.commit()


async def _upsert_message(
    db: AsyncSession,
    gc: GraphClient,
    conn: M365Connection,
    msg: dict,
    folder_hint: str,
) -> Optional[Email]:
    """Insert-or-update by `m365_message_id`. Returns the Email row or None if skipped."""
    m365_id = msg.get("id")
    if not m365_id:
        return None

    # Check existing row first.
    existing = await db.scalar(select(Email).where(Email.m365_message_id == m365_id))

    # Graph's "@removed" shape marks deletions in delta results.
    if msg.get("@removed"):
        if existing:
            await db.delete(existing)
        return None

    categories = msg.get("categories") or []
    is_private = settings.M365_IGNORE_CATEGORY in categories

    from_rec = (msg.get("from") or {}).get("emailAddress") or {}
    from_address = (from_rec.get("address") or "").strip().lower()
    from_name = from_rec.get("name")

    to_addresses = _parse_recipients(msg.get("toRecipients"))
    cc_addresses = _parse_recipients(msg.get("ccRecipients"))

    sent_at = _parse_iso(msg.get("sentDateTime"))
    received_at = _parse_iso(msg.get("receivedDateTime")) or datetime.now(timezone.utc)

    subject = msg.get("subject") or ""
    conversation_id = msg.get("conversationId") or m365_id
    internet_message_id = msg.get("internetMessageId")

    if is_private:
        body_html: Optional[str] = None
        body_text: Optional[str] = None
        body_preview = None
        has_attachments = False
    else:
        body = msg.get("body") or {}
        raw_html = body.get("content") or ""
        # bleach sanitize/parse is sync CPU work — offload off the event loop.
        body_html = (
            await asyncio.to_thread(sanitize_html, raw_html)
            if body.get("contentType") == "html"
            else None
        )
        body_text = (
            await asyncio.to_thread(html_to_text, raw_html)
            if not body_html
            else await asyncio.to_thread(html_to_text, body_html)
        )
        if body.get("contentType") == "text" and not body_html:
            body_text = raw_html
        body_preview = (msg.get("bodyPreview") or "")[:255]
        has_attachments = bool(msg.get("hasAttachments"))

    direction = (
        EmailDirection.sent
        if folder_hint.lower() == "sentitems"
        or (from_address and from_address == conn.mailbox_upn.lower())
        else EmailDirection.received
    )

    # Matching (skip for private-filtered).
    if existing and existing.candidate_id is not None:
        match_method = existing.match_method
        match_confidence = existing.match_confidence
        matched_at = existing.matched_at
        candidate_id = existing.candidate_id
    elif is_private:
        match_method = EmailMatchMethod.unmatched
        match_confidence = None
        matched_at = None
        candidate_id = None
    else:
        dto = IncomingMessage(
            from_address=from_address,
            to_addresses=[r["address"] for r in to_addresses if r.get("address")],
            cc_addresses=[r["address"] for r in cc_addresses if r.get("address")],
            subject=subject,
            conversation_id=conversation_id,
        )
        m = await matcher.match(db, dto)
        candidate_id = m.candidate_id
        match_method = EmailMatchMethod(m.method)
        match_confidence = m.confidence
        matched_at = datetime.now(timezone.utc) if m.candidate_id is not None else None

    if existing is None:
        row = Email(
            user_id=conn.user_id,
            candidate_id=candidate_id,
            m365_message_id=m365_id,
            m365_internet_message_id=internet_message_id,
            m365_conversation_id=conversation_id,
            subject=subject[:998] if subject else None,
            from_address=from_address,
            from_name=from_name,
            to_addresses=to_addresses,
            cc_addresses=cc_addresses,
            body_html=body_html,
            body_text=body_text,
            body_preview=body_preview,
            sent_at=sent_at,
            received_at=received_at,
            direction=direction,
            has_attachments=has_attachments,
            is_read=bool(msg.get("isRead")),
            is_private_filtered=is_private,
            match_method=match_method,
            match_confidence=match_confidence,
            matched_at=matched_at,
            raw_categories=categories,
        )
        db.add(row)
        await db.flush()
    else:
        existing.is_read = bool(msg.get("isRead"))
        existing.body_html = body_html
        existing.body_text = body_text
        existing.body_preview = body_preview
        existing.has_attachments = has_attachments
        existing.raw_categories = categories
        existing.is_private_filtered = is_private
        if candidate_id != existing.candidate_id:
            existing.candidate_id = candidate_id
            existing.match_method = match_method
            existing.match_confidence = match_confidence
            existing.matched_at = matched_at
        row = existing

    # Attachments — only for non-filtered messages and when we actually have any.
    if not is_private and has_attachments:
        try:
            atts = await attachment_handler.download_for_email(db, gc, row)
            for att in atts:
                if att.is_cv_candidate and row.candidate_id is not None:
                    await attachment_handler.try_parse_cv(db, att, row)
        except Exception:  # noqa: BLE001
            logger.exception("attachment handling failed for email %s", row.id)

    return row


def _parse_recipients(value) -> list[dict]:
    """Graph `toRecipients` → `[{address, name}, ...]`."""
    out: list[dict] = []
    if not value:
        return out
    for r in value:
        ea = (r or {}).get("emailAddress") or {}
        addr = (ea.get("address") or "").strip().lower()
        if addr:
            out.append({"address": addr, "name": ea.get("name")})
    return out


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        # Graph returns UTC with Z or +00:00 — isoformat handles both in 3.11+.
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# ── Events ──────────────────────────────────────────────────────────────────


async def _sync_events(
    db: AsyncSession,
    gc: GraphClient,
    conn: M365Connection,
    result: SyncResult,
) -> None:
    """Pull calendar events via delta view around today ± 1 year."""
    if conn.delta_token_events:
        url = conn.delta_token_events
        params = None
    else:
        now = datetime.now(timezone.utc)
        url = "/me/calendarView/delta"
        # Graph rejects $top on calendarView/delta — must use Prefer header instead.
        # Paging defaults to server-chosen size and pagination_iter handles @odata.nextLink.
        params = {
            "startDateTime": (now - timedelta(days=365)).isoformat(),
            "endDateTime": (now + timedelta(days=365)).isoformat(),
            "$select": EVENT_SELECT,
        }

    last_delta_link: Optional[str] = None
    try:
        async for page in gc.paginate(url, params=params):
            for ev in page.get("value", []):
                try:
                    if await _upsert_event(db, conn, ev):
                        result.events_ingested += 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Failed to ingest event %s", ev.get("id"))
                    result.errors += 1
                    if len(result.error_samples) < 20:
                        result.error_samples.append(f"event: {exc!r}")
            await db.commit()
            if page.get("@odata.deltaLink"):
                last_delta_link = page["@odata.deltaLink"]
    except GraphRequestError as exc:
        if exc.status == 410:
            logger.warning("Event delta 410 for %s — resetting token", conn.id)
            conn.delta_token_events = None
            await db.commit()
            return
        raise

    if last_delta_link:
        conn.delta_token_events = last_delta_link
        await db.commit()


async def _upsert_event(db: AsyncSession, conn: M365Connection, ev: dict) -> bool:
    graph_id = ev.get("id")
    if not graph_id:
        return False

    existing = await db.scalar(
        select(CalendarEvent).where(
            CalendarEvent.external_source == M365_SOURCE,
            CalendarEvent.external_id == graph_id,
        )
    )

    if ev.get("@removed") or ev.get("isCancelled"):
        if existing:
            existing.status = EventStatus.cancelled
            await maybe_remove_calendar_handoff(
                db,
                candidate_id=existing.candidate_id,
                job_id=existing.job_id,
                event_id=existing.id,
                actor_user_id=conn.user_id,
                occurred_at=datetime.now(timezone.utc),
            )
        return False

    change_key = ev.get("changeKey")
    if existing and existing.m365_change_key == change_key:
        return False  # nothing changed — skip

    start = _parse_graph_datetime((ev.get("start") or {}).get("dateTime"))
    end = _parse_graph_datetime((ev.get("end") or {}).get("dateTime"))
    if start is None:
        return False

    subject = (ev.get("subject") or "Spotkanie")[:255]
    location_name = (ev.get("location") or {}).get("displayName") or None
    description = (ev.get("body") or {}).get("content")

    attendees_raw = ev.get("attendees") or []
    attendee_rows = []
    for a in attendees_raw:
        ea = (a or {}).get("emailAddress") or {}
        addr = (ea.get("address") or "").strip().lower()
        if addr:
            attendee_rows.append({"address": addr, "name": ea.get("name")})

    # Link to candidate if any attendee matches.
    candidate_id: Optional[int] = None
    if attendee_rows:
        from app.models.candidate import Candidate

        addrs = [a["address"] for a in attendee_rows]
        cand = await db.scalar(select(Candidate).where(Candidate.email.in_(addrs)))
        if cand:
            candidate_id = cand.id

    if existing is None:
        row = CalendarEvent(
            title=subject,
            description=description,
            event_type=EventType.meeting,
            start_time=start,
            end_time=end,
            all_day=False,
            location=location_name,
            attendees=attendee_rows,
            candidate_id=candidate_id,
            status=EventStatus.scheduled,
            external_source=M365_SOURCE,
            external_id=graph_id,
            m365_change_key=change_key,
            m365_series_master_id=ev.get("seriesMasterId"),
            created_by=conn.user_id,
        )
        db.add(row)
    else:
        existing.title = subject
        existing.description = description
        existing.start_time = start
        existing.end_time = end
        existing.location = location_name
        existing.attendees = attendee_rows
        existing.m365_change_key = change_key
        existing.m365_series_master_id = ev.get("seriesMasterId")
        if candidate_id and existing.candidate_id is None:
            existing.candidate_id = candidate_id

    return True


def _parse_graph_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
