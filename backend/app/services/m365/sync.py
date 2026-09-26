"""Per-connection sync orchestrator.

Called by `backend/app/tasks/microsoft365_sync.py` every `M365_SYNC_INTERVAL_SECONDS`,
and by `/api/microsoft365/callback` as an asyncio task for the initial backfill.

Strategy:
- Messages: delta query over `/me/mailFolders/Inbox/messages` + `/SentItems`.
  First run (no delta token) = backfill with `$filter=receivedDateTime ge <12mo>`.
- Events: delta query over `/me/calendarView/delta?startDateTime=..&endDateTime=..`.
- Both persist their `@odata.deltaLink` for the next iteration.

Kursor delta NIE przesuwa się po przebiegu z błędami (INT-01, audyt 14.09.2026).
Graph oddaje `@odata.deltaLink` wyłącznie na OSTATNIEJ stronie okna, więc zapis
tego linku jest potwierdzeniem „całe okno wchłonięte". Do 09.2026 kursor był
zapisywany także wtedy, gdy część wiadomości (albo cała strona przy padniętym
commicie) przepadła — Graph już tych zmian nie oddawał, a `last_sync_status`
mówił `idle`, więc sonda `checks.m365` niczego nie widziała. Teraz folder
z błędami zostawia kursor bez zmian (upserty są idempotentne po
`m365_message_id` / `external_id`, więc powtórka okna nie dubluje wierszy),
a przebieg z błędami kończy się statusem `error`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Hard ceiling on a single sync pass — guards against a hung Graph call
# holding the DB connection and poisoning the pool.
_SYNC_TIMEOUT_SECONDS = 8 * 60

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.encryption import TokenCipherNotConfigured
from app.models.app_setting import AppSetting
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
from app.services.calendar_all_day import normalize_all_day
from app.services.calendar_privacy import (
    PRIVATE_EVENT_FIELDS,
    is_private_marker,
    is_scrubbed,
)
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
    "organizer,attendees,location,seriesMasterId,type,isCancelled,isAllDay,"
    "sensitivity"
)
# Stary kursor delty pamięta $select, z którym powstał — bez `sensitivity`
# prywatne spotkania dalej przychodziłyby jako zwykłe. Każde połączenie robi
# raz pełny odczyt okna ± 1 rok zamiast delty (znacznik w `app_settings`),
# a zapisane już prywatne spotkania dostają przy tym treść „Spotkanie
# prywatne” (R3-7).
EVENT_SELECT_RESET_KEY = "m365_event_select_sensitivity_reset"


@dataclass
class SyncResult:
    connection_id: int
    messages_ingested: int = 0
    attachments_downloaded: int = 0
    events_ingested: int = 0
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)
    #: Przebieg NIE ruszył, bo ta sama skrzynka była już synchronizowana.
    #: Odróżnia „nic nie przyszło" od „w ogóle nie pytaliśmy" — bez tego pola
    #: odmowa jest nieodróżnialna od pustego, udanego syncu.
    skipped_already_running: bool = False


# ── Bramka „jedna synchronizacja na skrzynkę" ──────────────────────────────
#
# Do sierpnia 2026 `last_sync_status = running` był ZAPISYWANY i przez nic
# nie CZYTANY, więc nic w systemie nie potrafiło stwierdzić, że skrzynka jest
# już synchronizowana. Cztery ścieżki wołają `sync_connection` i wszystkie
# mogą trafić na siebie: zaplanowana pętla (co 300 s), backfill z callbacku
# OAuth (`trigger_backfill`, potrafi trwać ponad godzinę przy 12 miesiącach
# historii), `_webhook_dispatch_sync` oraz `POST /sync/trigger` (rate limit
# 10/min i żadnej innej bramki). Dwa równoległe przebiegi tej samej skrzynki
# podwajają ruch do Graph, ścigają się na kursorze delta, a przy kolizji na
# UNIQUE `emails.m365_message_id` zatruwały sesję tak, że commit strony
# odrzucał całą stronę maili.
#
# Mutex jest W PROCESIE, a nie w bazie — świadomie. Wariant bazowy wymaga
# kolumny `last_sync_started_at` (bez niej nie da się odróżnić przebiegu
# TRWAJĄCEGO od porzuconego przez restart kontenera, a sam warunek
# `status == running` zamurowałby skrzynkę na zawsze po każdym redeployu
# w trakcie backfillu), czyli migracji. Wszystkie cztery ścieżki żyją w tym
# samym procesie aplikacji, więc lock je pokrywa; przy przejściu na wiele
# workerów (patrz uwaga o leader-election dla pętli tła) trzeba dołożyć
# wariant bazodanowy.
_sync_locks: dict[int, asyncio.Lock] = {}


# Runda 6 audytu: webhook, który trafił na trwający przebieg tej skrzynki,
# był odrzucany, a jego klucz replay i tak trafiał do cache jako obsłużony —
# nowa wiadomość czekała do następnego tiku pętli (albo przepadała, gdy kursor
# delty strony był już za nią). Teraz taki webhook zostawia tu prośbę o
# jeszcze jeden przebieg: ustawia ``sync_connection(resync_if_busy=True)``,
# czyta i czyści trwający przebieg zaraz po swoim końcu (pod tym samym lockiem).
_resync_requested: set[int] = set()
# Sufit dodatkowych przebiegów pod jednym lockiem — seria webhooków w trakcie
# każdego kolejnego przebiegu nie może trzymać skrzynki w nieskończoność.
_MAX_TRAILING_RESYNCS = 3


def _connection_lock(connection_id: int) -> asyncio.Lock:
    """Lock per połączenie. Słownik jest malutki (jeden wpis na skrzynkę)."""
    lock = _sync_locks.get(connection_id)
    if lock is None:
        lock = asyncio.Lock()
        _sync_locks[connection_id] = lock
    return lock


# ── Entry point ─────────────────────────────────────────────────────────────


async def sync_connection(
    db: AsyncSession, conn: M365Connection, *, resync_if_busy: bool = False
) -> SyncResult:
    """Run one full sync pass (messages + events) for the given connection.

    - Hard timeout (`_SYNC_TIMEOUT_SECONDS`) so a hung Graph call can't hold the
      DB connection open indefinitely.
    - `last_sync_at` is set on BOTH success and error so the scheduler's cutoff
      test behaves correctly (otherwise a failing row keeps being picked up
      every loop iteration).
    - Jedna synchronizacja na skrzynkę naraz (patrz `_sync_locks`). Drugi
      przebieg jest ODRZUCANY, a nie kolejkowany: kolejkowanie za trwającym
      12-miesięcznym backfillem zablokowałoby pętlę na godziny, a i tak
      chodziłoby o tę samą robotę.
    """
    result = SyncResult(connection_id=conn.id)
    if not await connection_owner_is_eligible(db, conn):
        logger.warning(
            "m365 sync refused for ineligible connection owner: connection_id=%s",
            conn.id,
        )
        return result

    lock = _connection_lock(conn.id)
    if lock.locked():
        # `locked()` + `async with` nie mają między sobą punktu zawieszenia
        # (nieobciążone `Lock.acquire` nie oddaje sterowania pętli zdarzeń),
        # więc dwa wywołania nie prześlizgną się tędy równocześnie.
        logger.info("m365 sync skipped: connection_id=%s is already syncing", conn.id)
        result.skipped_already_running = True
        if resync_if_busy:
            _resync_requested.add(conn.id)
        return result

    async with lock:
        _resync_requested.discard(conn.id)
        result = await _sync_connection_locked(db, conn, result)
        for _ in range(_MAX_TRAILING_RESYNCS):
            if conn.id not in _resync_requested:
                break
            _resync_requested.discard(conn.id)
            logger.info(
                "m365 sync: connection_id=%s — dodatkowy przebieg po webhooku "
                "z czasu trwającej synchronizacji",
                conn.id,
            )
            result = await _sync_connection_locked(
                db, conn, SyncResult(connection_id=conn.id)
            )
        return result


async def _sync_connection_locked(
    db: AsyncSession, conn: M365Connection, result: SyncResult
) -> SyncResult:
    """Właściwy przebieg — wołany wyłącznie z trzymanym lockiem połączenia."""
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
        # Cancellation can leave a flush transaction unusable. Roll it back
        # before recording failure, then reload attributes expired by rollback.
        await db.rollback()
        await db.refresh(conn)
        logger.warning("m365 sync_connection TIMEOUT for %s", conn.id)
        conn.last_sync_status = M365SyncStatus.error
        conn.last_error = f"timeout after {_SYNC_TIMEOUT_SECONDS}s"
        conn.last_sync_at = datetime.now(timezone.utc)
        result.errors += 1
        result.error_samples.append("top: asyncio.TimeoutError")
        await db.commit()
        from app.core.operation_telemetry import record_job_outcome

        record_job_outcome(
            "m365_sync",
            False,
            interval_seconds=max(60, settings.M365_SYNC_INTERVAL_SECONDS),
            subject_id=conn.id,
        )
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
        from app.core.operation_telemetry import record_job_outcome

        record_job_outcome(
            "m365_sync",
            False,
            interval_seconds=max(60, settings.M365_SYNC_INTERVAL_SECONDS),
            subject_id=conn.id,
        )
        return result
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        await db.refresh(conn)
        logger.exception("m365 sync_connection failed for %s", conn.id)
        conn.last_sync_status = M365SyncStatus.error
        conn.last_error = f"{exc!r}"[:2000]
        conn.last_sync_at = datetime.now(timezone.utc)
        result.errors += 1
        result.error_samples.append(f"top: {exc!r}")
        await db.commit()
        from app.core.operation_telemetry import record_job_outcome

        record_job_outcome(
            "m365_sync",
            False,
            interval_seconds=max(60, settings.M365_SYNC_INTERVAL_SECONDS),
            subject_id=conn.id,
        )
        return result

    if result.errors > 0:
        # Błędy per wiadomość/wydarzenie/strona są łapane w pętlach niżej,
        # żeby jeden zepsuty mail nie urwał reszty skrzynki — ale przebieg,
        # w którym coś przepadło, NIE jest udany. `idle` chowałby go przed
        # sondą `checks.m365` (czyta `last_sync_status`), a kursor folderów
        # z błędami został celowo w miejscu (patrz docstring modułu).
        sample = result.error_samples[0] if result.error_samples else ""
        conn.last_sync_status = M365SyncStatus.error
        conn.last_error = (
            f"{result.errors} błędów importu — kursor folderów z błędami "
            f"nie przesunięty. {sample}"
        ).strip()[:2000]
    else:
        conn.last_sync_status = M365SyncStatus.idle
    conn.last_sync_at = datetime.now(timezone.utc)
    await db.commit()
    from app.core.operation_telemetry import record_job_outcome

    record_job_outcome(
        "m365_sync",
        result.errors == 0,
        interval_seconds=max(60, settings.M365_SYNC_INTERVAL_SECONDS),
        subject_id=conn.id,
    )
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

    any_backfill = conn.backfill_completed_at is None

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
        # Only final deltaLinks acknowledge a completed folder. A nextLink
        # resumes an unfinished page sequence and must not complete backfill.
        if _is_valid_delta_link(conn.delta_token_inbox) and _is_valid_delta_link(
            conn.delta_token_sent
        ):
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


def _is_valid_page_link(url: Optional[str]) -> bool:
    """An opaque Graph nextLink can resume an unfinished delta round."""
    return bool(
        url and url.startswith("https://graph.microsoft.com/") and "$skiptoken=" in url
    )


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
    if _is_valid_delta_link(existing_cursor) or _is_valid_page_link(existing_cursor):
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
    # Błędy policzone PRZED tym folderem — kursor wolno zapisać tylko wtedy,
    # gdy ten przebieg folderu nie dołożył ani jednego (wiadomość ani commit
    # strony). Licznik jest wspólny dla całego przebiegu, więc porównujemy
    # różnicę, nie wartość bezwzględną.
    errors_before = result.errors
    connection_id = conn.id
    progress = {
        "event_kind": "m365_progress",
        "job": "m365_sync",
        "operation": "m365_messages_folder",
        "operation_id": str(uuid4()),
        "subject_id": connection_id,
        "folder": folder if folder in {"Inbox", "SentItems"} else "other",
        "release": os.getenv("GIT_SHA", "unknown"),
        "environment": os.getenv("SENTRY_ENVIRONMENT", "production"),
    }
    folder_started = time.monotonic()
    logger.info(
        "m365_folder_started",
        extra={
            **progress,
            "phase": "folder_started",
            "resume_kind": (
                "page"
                if _is_valid_page_link(existing_cursor)
                else "delta"
                if _is_valid_delta_link(existing_cursor)
                else "initial"
            ),
        },
    )
    page_number = 0

    async for page in gc.paginate(url, params=params):
        page_number += 1
        page_started = time.monotonic()
        page_errors_before = result.errors
        page_progress = {
            **progress,
            "page_number": page_number,
            "messages_seen": len(page.get("value", [])),
        }
        logger.info(
            "m365_page_started", extra={**page_progress, "phase": "page_started"}
        )
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
        # Ten commit stoi POZA `except` wyżej, więc na zatrutej sesji sam rzucał
        # wyjątkiem i cała strona maili przepadała, a wyjątek uciekał do
        # wywołującego (w ścieżce `/sync/trigger` — całkowicie niewidocznie,
        # jako „Task exception was never retrieved" dopiero przy GC).
        # Wstawienie maila siedzi teraz w SAVEPOINCIE, więc zatrucie sesji jest
        # znacznie mniej prawdopodobne; gdy jednak wystąpi, rollback przywraca
        # sesję do stanu używalnego i sync leci dalej zamiast się urwać.
        try:
            # Persist the resume point atomically with the page's rows. After
            # any error in this folder, retain the last clean page so retry
            # cannot skip a failed message, even if later pages succeed.
            next_link = page.get("@odata.nextLink")
            checkpoint_saved = result.errors == errors_before and _is_valid_page_link(
                next_link
            )
            if checkpoint_saved:
                setattr(conn, cursor_attr, next_link)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "m365 conn %s: page commit failed for %s — page dropped",
                connection_id,
                folder,
            )
            await db.rollback()
            await db.refresh(conn)
            result.errors += 1
            if len(result.error_samples) < 20:
                result.error_samples.append(f"page-commit: {exc!r}")
        else:
            # A started page is not proof of progress. Emit this only after
            # commit, and distinguish persisted rows from an advanced cursor.
            logger.info(
                "m365_page_committed",
                extra={
                    **page_progress,
                    "phase": "page_committed",
                    "checkpoint_saved": checkpoint_saved,
                    "page_errors": result.errors - page_errors_before,
                    "elapsed_ms": round((time.monotonic() - page_started) * 1000),
                },
            )
        if page.get("@odata.deltaLink"):
            last_delta_link = page["@odata.deltaLink"]

    if result.errors > errors_before:
        # The final deltaLink must not acknowledge a failed page. Keep the
        # last committed nextLink (or the original cursor if none succeeded).
        logger.warning(
            "m365 conn %s: %s had %d import error(s) — delta cursor NOT advanced",
            conn.id,
            folder,
            result.errors - errors_before,
        )
        return

    if last_delta_link and _is_valid_delta_link(last_delta_link):
        setattr(conn, cursor_attr, last_delta_link)
        await db.commit()
        logger.info(
            "m365_folder_completed",
            extra={
                **progress,
                "phase": "folder_completed",
                "pages_seen": page_number,
                "checkpoint_saved": True,
                "elapsed_ms": round((time.monotonic() - folder_started) * 1000),
            },
        )


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
            if existing.candidate_id is not None or existing.idempotency_key:
                # audyt 22.09 r2 (FIX-04): ``@removed`` przychodzi także przy
                # PRZENIESIENIU wiadomości do folderu, którego nie
                # synchronizujemy (Archiwum, własny folder). Mail powiązany
                # z kandydatem albo wysłany z NEXUSA jest historią pracy
                # z kandydatem — nie kasujemy go razem z powiązaniami.
                logger.info(
                    "m365 conn %s: email %s removed from %s in Outlook — kept "
                    "(linked to candidate or sent from NEXUS)",
                    conn.id,
                    existing.id,
                    folder_hint,
                )
            else:
                await db.delete(existing)
        return None

    if existing is None:
        # INT-14: identyfikator Graph NIE jest trwały — szkic wysłany z NEXUSA
        # dostaje nowe ID po przeniesieniu do Wysłanych (tak samo każda
        # wiadomość przeniesiona między folderami). Tożsamością wiadomości
        # w skrzynce jest ``internetMessageId``; bez tego dopasowania delta
        # Wysłanych zakładała drugi wiersz tej samej wysyłki.
        existing = await _adopt_by_internet_message_id(db, conn, msg, folder_hint)

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
    elif is_private or (existing is not None and matcher.manually_unlinked(existing)):
        # Runda 6 audytu: ręczne odpięcie jest decyzją — sync nie przypina
        # maila z powrotem przy każdej zmianie wiadomości w Outlooku.
        match_method = EmailMatchMethod.unmatched
        match_confidence = None
        matched_at = existing.matched_at if existing is not None else None
        candidate_id = None
    else:
        dto = IncomingMessage(
            from_address=from_address,
            to_addresses=[r["address"] for r in to_addresses if r.get("address")],
            cc_addresses=[r["address"] for r in cc_addresses if r.get("address")],
            subject=subject,
            conversation_id=conversation_id,
            owner_address=conn.mailbox_upn,
        )
        m = await matcher.match(db, dto)
        candidate_id = m.candidate_id
        match_method = EmailMatchMethod(m.method)
        match_confidence = m.confidence
        matched_at = datetime.now(timezone.utc) if m.candidate_id is not None else None

    if existing is None:
        row = _new_email_row(
            conn=conn,
            m365_id=m365_id,
            internet_message_id=internet_message_id,
            conversation_id=conversation_id,
            subject=subject,
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
            is_private=is_private,
            match_method=match_method,
            match_confidence=match_confidence,
            matched_at=matched_at,
            candidate_id=candidate_id,
            categories=categories,
        )
        try:
            # SAVEPOINT: `emails.m365_message_id` ma indeks UNIQUE, a to jest
            # SELECT-then-INSERT. Gdy ten sam mail wejdzie równolegle (drugi
            # przebieg, webhook, ponowienie), IntegrityError bez savepointu
            # zatruwa CAŁĄ sesję: dalsze wiadomości lecą na martwej sesji, a
            # commit strony odrzuca komplet zaciągniętych maili. Savepoint
            # ogranicza szkodę do jednej wiadomości.
            async with db.begin_nested():
                db.add(row)
                await db.flush()
        except IntegrityError:
            # Przegraliśmy wyścig — wiersz istnieje. Traktujemy to jak trafienie
            # w `existing` (upsert), a nie jak błąd: mail jest w bazie, więc
            # liczenie tego jako porażki wprowadzałoby w błąd raport syncu.
            logger.info(
                "m365 conn %s: message %s inserted concurrently — switching to update",
                conn.id,
                m365_id,
            )
            existing = await db.scalar(
                select(Email).where(Email.m365_message_id == m365_id)
            )
            if existing is None:
                # Druga strona wyścigu jeszcze nie zacommitowała — nie mamy na
                # czym pracować, następny przebieg delty dociągnie tę wiadomość.
                return None
            row = existing

    if existing is not None:
        row = _apply_email_update(
            existing,
            body_html=body_html,
            body_text=body_text,
            body_preview=body_preview,
            has_attachments=has_attachments,
            is_read=bool(msg.get("isRead")),
            is_private=is_private,
            categories=categories,
            candidate_id=candidate_id,
            match_method=match_method,
            match_confidence=match_confidence,
            matched_at=matched_at,
        )

    # Attachments — only for non-filtered messages and when we actually have any.
    if not is_private and has_attachments:
        # Download and persist the durable attachment row inside the page
        # transaction.  CV parsing may call external AI providers and used
        # to keep this Graph page open for minutes.  The dedicated worker
        # consumes the committed row after the page cursor is durable.
        #
        # INT-08: błąd listowania załączników NIE jest już połykany — pętla
        # strony liczy go jako błąd wiadomości, więc kursor delty stoi, a mail
        # (zapisany i tak razem ze stroną) wraca w następnym przebiegu.
        # Pojedynczy nieudany plik zostaje oznaczony ``download_failed[n]``
        # i ponawia go pętla ``m365_cv_parse``.
        await attachment_handler.download_for_email(db, gc, row)

    return row


async def _adopt_by_internet_message_id(
    db: AsyncSession,
    conn: M365Connection,
    msg: dict,
    folder_hint: str,
) -> Optional[Email]:
    """Znajdź wiersz tej samej wiadomości po ``internetMessageId`` i przepisz
    mu aktualne ID Graph. ``None`` = to naprawdę nowa wiadomość.

    Tylko w obrębie jednej skrzynki (``user_id``) — ta sama wiadomość
    u adresata w innej skrzynce NEXUSA jest osobnym wierszem. Przy kilku
    wierszach (duplikaty sprzed poprawki) bierzemy ten z kluczem wysyłki,
    potem najstarszy — tak samo jak jednorazowe sprzątanie.
    """
    internet_message_id = msg.get("internetMessageId")
    new_id = msg.get("id")
    if not internet_message_id or not new_id:
        return None
    # audyt 22.09 r2 (FIX-05): adopcja zależy od KIERUNKU. Mail wysłany
    # z własnym adresem w CC ma w skrzynce DWIE kopie z tym samym
    # ``internetMessageId`` (Wysłane + Odebrane). Bez tego kopia z Odebranych
    # przejmowała wiersz wysyłki, a jej usunięcie kasowało wysłanego maila.
    if folder_hint.lower() == "sentitems":
        direction_clause = or_(
            Email.idempotency_key.is_not(None),
            Email.direction == EmailDirection.sent,
        )
    else:
        direction_clause = and_(
            Email.idempotency_key.is_(None),
            Email.direction == EmailDirection.received,
        )
    twin = await db.scalar(
        select(Email)
        .where(
            Email.user_id == conn.user_id,
            Email.m365_internet_message_id == internet_message_id,
            direction_clause,
        )
        .order_by(Email.idempotency_key.is_(None), Email.id.asc())
        .limit(1)
    )
    if twin is None:
        return None
    twin_id = twin.id
    conversation_id = msg.get("conversationId")
    try:
        # SAVEPOINT: m365_message_id ma UNIQUE — równoległy przebieg mógł już
        # wstawić wiersz z nowym ID. Konflikt nie może zatruć sesji strony.
        async with db.begin_nested():
            twin.m365_message_id = new_id
            if conversation_id and (twin.m365_conversation_id or "").startswith(
                "pending:"
            ):
                twin.m365_conversation_id = conversation_id
            if twin.send_state in ("pending", "uncertain") and (
                folder_hint.lower() == "sentitems"
            ):
                # Wiadomość jest w Wysłanych — wynik wysyłki przestał być
                # niepewny.
                twin.send_state = "sent"
            await db.flush()
    except IntegrityError:
        logger.info(
            "m365 conn %s: email %s re-identification lost a race — skipping",
            conn.id,
            twin_id,
        )
        return None
    logger.info(
        "m365 conn %s: email %s re-identified by internetMessageId (id changed)",
        conn.id,
        twin_id,
    )
    return twin


def _new_email_row(
    *,
    conn: M365Connection,
    m365_id: str,
    internet_message_id: Optional[str],
    conversation_id: str,
    subject: str,
    from_address: str,
    from_name: Optional[str],
    to_addresses: list[dict],
    cc_addresses: list[dict],
    body_html: Optional[str],
    body_text: Optional[str],
    body_preview: Optional[str],
    sent_at: Optional[datetime],
    received_at: datetime,
    direction: EmailDirection,
    has_attachments: bool,
    is_read: bool,
    is_private: bool,
    match_method: EmailMatchMethod,
    match_confidence: Optional[float],
    matched_at: Optional[datetime],
    candidate_id: Optional[int],
    categories: list,
) -> Email:
    """Świeży wiersz `Email` — wydzielone, żeby konstrukcja mieściła się razem
    z `db.add` w bloku savepointu (obiekt dodany przed savepointem przeżyłby
    jego rollback i wysadził następny flush)."""
    return Email(
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
        is_read=is_read,
        is_private_filtered=is_private,
        match_method=match_method,
        match_confidence=match_confidence,
        matched_at=matched_at,
        raw_categories=categories,
    )


def _apply_email_update(
    existing: Email,
    *,
    body_html: Optional[str],
    body_text: Optional[str],
    body_preview: Optional[str],
    has_attachments: bool,
    is_read: bool,
    is_private: bool,
    categories: list,
    candidate_id: Optional[int],
    match_method: EmailMatchMethod,
    match_confidence: Optional[float],
    matched_at: Optional[datetime],
) -> Email:
    """Nadpisanie istniejącego wiersza świeżą treścią z Graph.

    Wydzielone bez zmiany zachowania, bo tę samą ścieżkę wykonuje teraz także
    przegrany wyścig na UNIQUE (INSERT → IntegrityError → SELECT → update).
    """
    existing.is_read = is_read
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
    return existing


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
    # Kursor sprzed `sensitivity` nie jest kasowany od razu: po nieudanym
    # przebiegu zostaje stary, a pełny odczyt powtórzy następny bieg.
    select_reset_pending = await _event_select_reset_pending(db, conn)
    # Pełny odczyt wymuszony TYLKO zmianą $select (kursor istniał). Ten odczyt
    # jest jednorazowy: wydarzenie, które psuje się trwale, nie może go
    # powtarzać w każdym biegu (audyt 25.09.2026, runda 4).
    forced_full_read = select_reset_pending and bool(conn.delta_token_events)
    if not select_reset_pending:
        # Dopiero po pełnym odczycie okna: ten przebieg obejmuje wyłącznie to,
        # co jest starsze niż okno, więc razem nie zostawiają luki.
        try:
            await _scrub_old_private_events(db, gc, conn)
        except Exception:  # noqa: BLE001 — nie blokuje synchronizacji kalendarza
            logger.exception("m365 conn %s: old private events scrub failed", conn.id)
    if conn.delta_token_events and not select_reset_pending:
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
    # Jak w `_sync_messages_for_folder`: kursor tylko po przebiegu bez błędów.
    errors_before = result.errors
    # Czy padło wydarzenie, które mogło zostać z prywatną treścią (prywatne
    # albo bez znanego `sensitivity`) — wtedy pełny odczyt musi się powtórzyć.
    private_failed = False
    try:
        async for page in gc.paginate(url, params=params):
            for ev in page.get("value", []):
                try:
                    if await _upsert_event(db, conn, ev):
                        result.events_ingested += 1
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Failed to ingest event %s", ev.get("id"))
                    if not ev.get("@removed") and (
                        is_private_marker(ev.get("sensitivity"))
                        or not ev.get("sensitivity")
                    ):
                        private_failed = True
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

    if result.errors > errors_before:
        if forced_full_read and last_delta_link and not private_failed:
            # Jednorazowy odczyt po zmianie $select dobiegł końca, a wszystkie
            # błędy dotyczą zwykłych (nieprywatnych) wydarzeń, które NEXUS
            # zna z wcześniejszych biegów. Stary kursor nie niesie
            # `sensitivity`, więc „zostać na nim” znaczyłoby pełny odczyt co
            # bieg — przyjmujemy nowy kursor, a dalsze błędy obsługuje delta.
            logger.warning(
                "m365 conn %s: forced events re-read had %d import error(s) "
                "(non-private) — new delta cursor stored",
                conn.id,
                result.errors - errors_before,
            )
            conn.delta_token_events = last_delta_link
            await _mark_event_select_reset(db, conn)
            await db.commit()
            return
        logger.warning(
            "m365 conn %s: events had %d import error(s) — delta cursor NOT advanced",
            conn.id,
            result.errors - errors_before,
        )
        return

    if last_delta_link:
        conn.delta_token_events = last_delta_link
        if select_reset_pending:
            await _mark_event_select_reset(db, conn)
        await db.commit()


async def _event_select_reset_pending(db: AsyncSession, conn: M365Connection) -> bool:
    """Czy kursor delty tego połączenia powstał jeszcze bez `sensitivity`."""
    row = await db.get(AppSetting, EVENT_SELECT_RESET_KEY)
    done = (row.value or {}).get("connection_ids") if row is not None else None
    return conn.id not in set(done or [])


async def _mark_event_select_reset(db: AsyncSession, conn: M365Connection) -> None:
    # Upsert w bazie — dwie skrzynki kończące pełny odczyt naraz nie mogą
    # wywrócić się na UNIQUE klucza ani nadpisać sobie listy.
    stmt = pg_insert(AppSetting).values(
        key=EVENT_SELECT_RESET_KEY, value={"connection_ids": [conn.id]}
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={
                "value": func.jsonb_build_object(
                    "connection_ids",
                    func.coalesce(
                        AppSetting.value["connection_ids"],
                        func.jsonb_build_array(),
                    ).op("||")(func.jsonb_build_array(conn.id)),
                ),
                "updated_at": func.now(),
            },
        )
    )


def _created_in_nexus(event: CalendarEvent) -> bool:
    """Czy wiersz powstał w NEXUSIE (a nie z importu Outlooka).

    ``operational_owner_id`` ustawiają WYŁĄCZNIE ścieżki zakładające wydarzenie
    w NEXUSIE (zaproszenie z formularza, prep w Teams, spotkanie po rozmowie,
    potwierdzony termin u klienta); import z Outlooka go nie ustawia, a edycja
    wydarzenia (``CalendarEventUpdate``) go nie przyjmuje — pilnuje tego test.
    """
    return getattr(event, "operational_owner_id", None) is not None


# Prywatne spotkania starsze niż okno pełnego odczytu (± 1 rok) — jednorazowy
# przebieg po id w Graphie, paczkami, z kursorem per połączenie.
OLD_PRIVATE_SCRUB_KEY_PREFIX = "m365_old_private_scrub:"
OLD_PRIVATE_SCRUB_BATCH = 100
EVENT_WINDOW_DAYS = 365


def _old_private_candidates_stmt(*, user_id: int, after_id: int):
    """Wiersze zaimportowane z Outlooka tej skrzynki, starsze niż okno."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=EVENT_WINDOW_DAYS)
    return (
        select(CalendarEvent)
        .where(
            CalendarEvent.external_source == M365_SOURCE,
            CalendarEvent.external_id.is_not(None),
            CalendarEvent.created_by == user_id,
            CalendarEvent.operational_owner_id.is_(None),
            CalendarEvent.start_time < cutoff,
            CalendarEvent.id > after_id,
        )
        .order_by(CalendarEvent.id)
        .limit(OLD_PRIVATE_SCRUB_BATCH)
    )


async def _scrub_old_private_events(
    db: AsyncSession, gc: GraphClient, conn: M365Connection
) -> None:
    """Czyści prywatne spotkania starsze niż okno pełnego odczytu.

    Pełny odczyt po dodaniu ``sensitivity`` obejmuje wyłącznie ± 1 rok, więc
    prywatne spotkania zaimportowane wcześniej zostawały z tematem, opisem
    i uczestnikami (audyt 25.09.2026, runda 4). Zamiast poszerzać okno delty
    (odczyt całej historii kalendarza i nowy kursor na lata wstecz) pytamy
    Graph o ``sensitivity`` wyłącznie tych wierszy — po id, paczkami, z
    kursorem. Zwykłe spotkania zostają nietknięte; 404 (usunięte w Outlooku)
    zostawia wiersz bez zmian. Inny błąd Graphu kończy przebieg na tym
    wierszu, następny bieg zaczyna od niego.
    """
    key = f"{OLD_PRIVATE_SCRUB_KEY_PREFIX}{conn.id}"
    state_row = await db.get(AppSetting, key)
    state = dict(state_row.value or {}) if state_row is not None else {}
    if state.get("done"):
        return
    after_id = int(state.get("after_id") or 0)
    rows = list(
        (
            await db.scalars(
                _old_private_candidates_stmt(user_id=conn.user_id, after_id=after_id)
            )
        ).all()
    )
    done = len(rows) < OLD_PRIVATE_SCRUB_BATCH
    for row in rows:
        if not is_scrubbed(row):
            try:
                ev = await gc.get(
                    f"/me/events/{row.external_id}",
                    params={"$select": "sensitivity"},
                )
            except GraphRequestError as exc:
                if exc.status not in (404, 410):
                    logger.warning(
                        "m365 conn %s: old private scrub stopped — Graph %s",
                        conn.id,
                        exc.status,
                    )
                    done = False
                    break
                ev = None
            if ev and is_private_marker(ev.get("sensitivity")):
                for field_name, value in PRIVATE_EVENT_FIELDS.items():
                    setattr(row, field_name, value)
                row.attendees = []
                # R7-V1-7: powiązanie z kandydatem pochodziło z uczestników.
                row.candidate_id = None
        after_id = row.id

    value = {"after_id": after_id, "done": done}
    stmt = pg_insert(AppSetting).values(key=key, value=value)
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": stmt.excluded.value, "updated_at": func.now()},
        )
    )
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

    # Prywatne w Outlooku = w NEXUSIE sam termin. Dotyczy spotkań z Outlooka;
    # wydarzenie założone w NEXUSIE (prep, rozmowa u klienta) niesie treść
    # NEXUSA, nie prywatną treść Outlooka. Rozstrzyga POCHODZENIE wiersza, nie
    # typ — typ da się zmienić w NEXUSIE, więc spotkanie z Outlooka
    # przestawione na „rozmowę” odzyskiwało prywatną treść przy najbliższej
    # zmianie w Outlooku (audyt 25.09.2026, runda 4).
    private = is_private_marker(ev.get("sensitivity")) and (
        existing is None or not _created_in_nexus(existing)
    )
    change_key = ev.get("changeKey")
    if (
        existing
        and existing.m365_change_key == change_key
        and (not private or (is_scrubbed(existing) and existing.candidate_id is None))
    ):
        return False  # nothing changed — skip

    fields = _graph_event_fields(ev)
    if fields is None:
        return False

    attendee_rows = []
    if private:
        # Prywatne spotkanie = sam zajęty termin (R3-7). Bez uczestników nie
        # ma też powiązania z kandydatem po adresie.
        fields.update(PRIVATE_EVENT_FIELDS)
    else:
        for a in ev.get("attendees") or []:
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
            **fields,
            event_type=EventType.meeting,
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
        for field, value in fields.items():
            setattr(existing, field, value)
        existing.attendees = attendee_rows
        existing.m365_change_key = change_key
        existing.m365_series_master_id = ev.get("seriesMasterId")
        if private:
            # Runda 7 (R7-V1-7): spotkanie, które stało się prywatne, nie może
            # zostać przypięte do kandydata — powiązanie pochodziło z
            # uczestników, których już nie trzymamy, a profil kandydata i
            # usunięcie osoby zdradzały, z kim było prywatne spotkanie.
            existing.candidate_id = None
        elif candidate_id and existing.candidate_id is None:
            existing.candidate_id = candidate_id

    return True


def _graph_event_fields(ev: dict) -> Optional[dict]:
    """Pola wydarzenia, które należą do Outlooka — wspólne dla insert i update.

    Dwie osobne listy przypisań rozjeżdżały się: `all_day` było stałym
    `False` przy wstawianiu i nie istniało przy aktualizacji, więc urlop
    z Outlooka zostawał 24-godzinnym blokiem na zawsze. `None` = wydarzenie
    bez czytelnego startu (pomijamy).
    """
    start = _parse_graph_datetime((ev.get("start") or {}).get("dateTime"))
    end = _parse_graph_datetime((ev.get("end") or {}).get("dateTime"))
    if start is None:
        return None
    all_day = bool(ev.get("isAllDay"))
    if all_day:
        start, end = normalize_all_day(start, end)
    return {
        "title": (ev.get("subject") or "Spotkanie")[:255],
        "description": (ev.get("body") or {}).get("content"),
        "start_time": start,
        "end_time": end,
        "all_day": all_day,
        "location": (ev.get("location") or {}).get("displayName") or None,
    }


def _parse_graph_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
