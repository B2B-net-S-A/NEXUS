"""
Saved-search alerts — background scanner (V2).

Re-executes every saved candidate search with ``notify_new_matches`` enabled
and notifies the OWNER about candidates that newly match — including EXISTING
candidates whose row changed into the match set (updated CV / skill / status),
not just brand-new rows.

Two anti-noise safeguards (the user explicitly asked for these):

1. **Baseline seed.** The first scan after the bell is enabled
   (``last_scanned_at IS NULL``) records every currently-matching candidate
   in ``saved_search_alert_log`` WITHOUT alerting. So a candidate that already
   matched never fires a "new match" alert later just because a background job
   (LinkedIn sync, experience backfill) touched its row.
2. **Alert-once dedup log.** Each ``(saved_search_id, candidate_id)`` pair is
   logged at most once (UNIQUE + ON CONFLICT DO NOTHING). A mass update that
   touches thousands of already-matching rows therefore produces zero alerts.

Incremental scan: replays the search through the REAL ``GET /api/candidates``
(in-process httpx ``ASGITransport`` + JWT minted for the owner → zero
filter-semantics drift) with ``updated_after = last_scanned_at`` on top, so it
only re-checks rows changed since the last pass. Each returned match absent
from the log is a genuine transition into the match set → alert + log.

Notification: one AGGREGATE row per search per run (type
``saved_search_match``), deduped per day via ``ix_notif_dedup_daily`` with
``dedupe_resurface=True``. Realtime push through the WS manager.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = max(
    300, int(os.getenv("SAVED_SEARCH_ALERTS_INTERVAL_SECONDS", "1800"))
)
_PAGE_SIZE = 100  # GET /api/candidates hard cap (le=100)
_MAX_PAGES = int(os.getenv("SAVED_SEARCH_ALERTS_MAX_PAGES", "20"))  # bound per run
_NAMES_IN_MESSAGE = 3

# Params we never replay from the stored snapshot: paging/sort is forced by
# the scanner, and the heavy include_* extras only matter for the list UI.
_DROPPED_PARAMS = {
    "page",
    "page_size",
    "sort",
    "id_after",
    "updated_after",
    "include_match_stats",
    "include_active_recruitments",
    "include_last_activity",
    "match_threshold",
    "profile_id",
}


def build_base_params(api_params: dict) -> dict[str, Any]:
    """Sanitize stored API params for replay: drop nulls + scanner-owned keys,
    then force newest-first paging. Page number / ``updated_after`` are added
    per call by the pager."""
    params: dict[str, Any] = {
        k: v
        for k, v in api_params.items()
        if k not in _DROPPED_PARAMS and v is not None
    }
    params["page_size"] = _PAGE_SIZE
    params["sort"] = "newest"
    return params


def polish_candidates(n: int) -> str:
    """`1 nowy kandydat` / `3 nowi kandydaci` / `7 nowych kandydatów`."""
    if n == 1:
        return "1 nowy kandydat"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} nowi kandydaci"
    return f"{n} nowych kandydatów"


def build_link(filters: Optional[dict], search_id: int) -> str:
    """Deep-link opening /candidates with the saved filters + `ss` marker so
    the FE re-applies the search and highlights the new rows."""
    qs = (filters or {}).get("qs")
    if isinstance(qs, str) and qs:
        return f"/candidates?{qs}&ss={search_id}"
    return f"/candidates?ss={search_id}"


def _full_name(item: dict) -> str:
    name = f"{(item.get('name') or '').strip()} {(item.get('lastname') or '').strip()}"
    return name.strip() or f"#{item.get('id')}"


async def _replay_match_items(
    client, token: str, params: dict, *, max_pages: int = _MAX_PAGES
) -> list[dict]:
    """Page through GET /api/candidates with the given params, returning the
    candidate items (id/name/lastname). Bounded by ``max_pages`` so a very
    broad search can't make one scan unbounded."""
    items: list[dict] = []
    headers = {"Authorization": f"Bearer {token}"}
    for page in range(1, max_pages + 1):
        resp = await client.get(
            "/api/candidates",
            params={**params, "page": page},
            headers=headers,
        )
        resp.raise_for_status()
        data = resp.json()
        batch = data.get("items") or []
        items.extend(batch)
        if len(batch) < _PAGE_SIZE:
            break
    else:
        logger.warning(
            "saved_search_alerts: hit max_pages=%d — broad search, tail not scanned",
            max_pages,
        )
    return items


async def _logged_candidate_ids(db, search_id: int, ids: list[int]) -> set[int]:
    """Return the subset of ``ids`` already present in the dedup log for this
    search."""
    if not ids:
        return set()
    from app.models.saved_search_alert_log import SavedSearchAlertLog

    rows = await db.execute(
        select(SavedSearchAlertLog.candidate_id).where(
            SavedSearchAlertLog.saved_search_id == search_id,
            SavedSearchAlertLog.candidate_id.in_(ids),
        )
    )
    return {r[0] for r in rows.all()}


async def _log_candidates(
    db, search_id: int, ids: list[int], *, notified_at: Optional[datetime]
) -> None:
    """Insert dedup-log rows (ON CONFLICT DO NOTHING). ``notified_at`` is NULL
    for the baseline seed, a timestamp when we actually alerted."""
    if not ids:
        return
    from app.models.saved_search_alert_log import SavedSearchAlertLog

    stmt = (
        pg_insert(SavedSearchAlertLog)
        .values(
            [
                {
                    "saved_search_id": search_id,
                    "candidate_id": cid,
                    "notified_at": notified_at,
                }
                for cid in ids
            ]
        )
        .on_conflict_do_nothing(constraint="uq_saved_search_alert_pair")
    )
    await db.execute(stmt)


async def _baseline_one(client, db, ss, owner) -> None:
    """First run after enable: seed the log with current matchers, NO alert."""
    api_params = (ss.filters or {}).get("api")
    if not isinstance(api_params, dict):
        logger.warning(
            "saved_search_alerts: search %s alerts on but no filters.api — skipping",
            ss.id,
        )
        return
    from app.core.security import create_access_token

    token = create_access_token(
        subject=owner.id, role=getattr(owner.role, "value", str(owner.role))
    )
    scan_start = datetime.now(timezone.utc)
    items = await _replay_match_items(client, token, build_base_params(api_params))
    ids = [int(it["id"]) for it in items]
    await _log_candidates(db, ss.id, ids, notified_at=None)
    ss.last_scanned_at = scan_start
    await db.flush()
    logger.info(
        "saved_search_alerts: baselined search %s (%d current matchers seeded)",
        ss.id,
        len(ids),
    )


async def _incremental_one(client, db, ss, owner) -> bool:
    """Steady-state run: alert about matches that changed since last scan and
    aren't already logged. Returns True when a notification was sent."""
    from app.api.notifications import create_notification
    from app.api.ws import notify_user as ws_notify_user
    from app.core.security import create_access_token
    from app.models.notification import NotificationType

    api_params = (ss.filters or {}).get("api")
    if not isinstance(api_params, dict):
        logger.warning(
            "saved_search_alerts: search %s alerts on but no filters.api — skipping",
            ss.id,
        )
        return False

    token = create_access_token(
        subject=owner.id, role=getattr(owner.role, "value", str(owner.role))
    )
    scan_start = datetime.now(timezone.utc)
    params = build_base_params(api_params)
    params["updated_after"] = ss.last_scanned_at.isoformat()
    items = await _replay_match_items(client, token, params)

    # Advance the watermark even when nothing new — a quiet pass still moves
    # time forward so the next run's window starts here (at-least-once: we use
    # scan_start captured before the query, so rows touched mid-scan re-appear).
    ss.last_scanned_at = scan_start

    if not items:
        await db.flush()
        return False

    by_id = {int(it["id"]): it for it in items}
    seen = await _logged_candidate_ids(db, ss.id, list(by_id))
    fresh_ids = [cid for cid in by_id if cid not in seen]
    if not fresh_ids:
        await db.flush()
        return False

    await _log_candidates(db, ss.id, fresh_ids, notified_at=scan_start)

    new_count = len(fresh_ids)
    unseen_total = (ss.unseen_count or 0) + new_count
    sample = [by_id[cid] for cid in fresh_ids[:_NAMES_IN_MESSAGE]]
    names = ", ".join(_full_name(it) for it in sample)
    extra = unseen_total - min(new_count, _NAMES_IN_MESSAGE)
    message = names + (f" i {extra} więcej" if extra > 0 else "")

    notif = await create_notification(
        db,
        user_id=ss.user_id,
        title=f"Nowi kandydaci: {ss.name}",
        message=(
            f"{polish_candidates(unseen_total)} pasuje do zapisanego"
            f" wyszukiwania. {message}"
        ),
        notification_type=NotificationType.saved_search_match,
        link=build_link(ss.filters, ss.id),
        related_entity_type="saved_search",
        related_entity_id=ss.id,
        dedupe_resurface=True,
    )
    ss.unseen_count = unseen_total
    await db.flush()

    try:
        await ws_notify_user(
            ss.user_id,
            {
                "type": "notification",
                "data": {
                    "id": notif.id,
                    "title": notif.title,
                    "message": notif.message,
                    "link": notif.link,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            },
        )
    except Exception as e:  # noqa: BLE001 — WS push is best-effort
        logger.debug(
            "saved_search_alerts: ws push failed for user %s: %s", ss.user_id, e
        )
    return True


async def scan_once() -> int:
    """One scanner pass over all alert-enabled candidate searches.

    Returns the number of searches that produced a notification (baseline runs
    do not count — they only seed).
    """
    from httpx import ASGITransport, AsyncClient

    from app.core.database import AsyncSessionLocal

    # Deferred import — main.py imports this module inside lifespan, so a
    # top-level `from app.main import app` would be circular.
    from app.main import app
    from app.models.saved_search import SavedSearch
    from app.models.user import User

    notified = 0
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(SavedSearch, User)
                .join(User, User.id == SavedSearch.user_id)
                .where(
                    SavedSearch.notify_new_matches.is_(True),
                    SavedSearch.entity == "candidates",
                    User.is_active.is_(True),
                )
                .order_by(SavedSearch.id)
            )
        ).all()
        if not rows:
            return 0

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://saved-search-scanner"
        ) as client:
            for ss, owner in rows:
                try:
                    if ss.last_scanned_at is None:
                        await _baseline_one(client, db, ss, owner)
                    elif await _incremental_one(client, db, ss, owner):
                        notified += 1
                    # Commit per search so one failure can't roll back the rest.
                    await db.commit()
                except Exception as e:  # noqa: BLE001 — isolate per-search failures
                    logger.warning(
                        "saved_search_alerts: search %s failed: %s", ss.id, e
                    )
                    await db.rollback()
    return notified


async def saved_search_alerts_loop(
    *, interval_seconds: int = _DEFAULT_INTERVAL_SECONDS
) -> None:
    """Long-running task: scan alert-enabled saved searches every N seconds."""
    logger.info("saved_search_alerts: started (interval=%ss)", interval_seconds)
    await asyncio.sleep(90)  # let the app warm up first
    while True:
        try:
            sent = await scan_once()
            if sent:
                logger.info("saved_search_alerts: notified %d searches", sent)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001 — keep the loop alive
            logger.warning("saved_search_alerts: pass failed: %s", e)
        await asyncio.sleep(interval_seconds)
