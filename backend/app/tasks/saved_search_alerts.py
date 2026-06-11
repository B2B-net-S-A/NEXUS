"""
Saved-search alerts — background scanner (V1).

Re-executes every saved candidate search with ``notify_new_matches`` enabled
and notifies the OWNER about candidates added after the search's PK watermark
(``last_seen_candidate_id``).

Architecture decision: the search is replayed through the REAL
``GET /api/candidates`` endpoint via an in-process ASGI client (httpx
``ASGITransport``) with a short-lived JWT minted for the owner. By
construction the scanner sees exactly what the owner would see in the UI —
zero filter-semantics drift, no 340-line filter builder duplicated. The
stored params come from the FE (``filters["api"]`` written by
``filtersToApiParams`` at save/toggle time); the scanner only forces paging,
sort and the ``id_after`` watermark on top.

State per saved search (model ``SavedSearch``):
- ``last_seen_candidate_id`` — watermark; only candidates with a higher id
  count as new. Initialized to MAX(candidates.id) when the alert is enabled.
- ``unseen_count`` — badge counter for the saved-searches menu; incremented
  here, reset by ``POST /api/saved-searches/{id}/viewed``.

Notification: one AGGREGATE row per search per run (type
``saved_search_match``), deduped per day via ``ix_notif_dedup_daily`` with
``dedupe_resurface=True`` — same-day finds update the existing entry instead
of piling up. Realtime push through the WS manager so the bell updates
immediately.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = max(
    300, int(os.getenv("SAVED_SEARCH_ALERTS_INTERVAL_SECONDS", "1800"))
)
_PAGE_SIZE = 100  # GET /api/candidates hard cap (le=100)
_NAMES_IN_MESSAGE = 3

# Params we never replay from the stored snapshot: paging/sort is forced by
# the scanner, and the heavy include_* extras only matter for the list UI.
_DROPPED_PARAMS = {
    "page",
    "page_size",
    "sort",
    "id_after",
    "include_match_stats",
    "include_active_recruitments",
    "include_last_activity",
    "match_threshold",
    "profile_id",
}


def build_scan_params(api_params: dict, last_seen_id: int) -> dict[str, Any]:
    """Sanitize stored API params for replay: drop nulls + scanner-owned keys,
    then force first-page/newest scan above the watermark."""
    params: dict[str, Any] = {
        k: v
        for k, v in api_params.items()
        if k not in _DROPPED_PARAMS and v is not None
    }
    params["page"] = 1
    params["page_size"] = _PAGE_SIZE
    params["sort"] = "newest"
    params["id_after"] = last_seen_id
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


async def _scan_one(client, db, ss, owner) -> bool:
    """Scan a single saved search; returns True when a notification was sent.

    Caller owns commit/rollback.
    """
    from app.api.notifications import create_notification
    from app.api.ws import notify_user as ws_notify_user
    from app.core.security import create_access_token
    from app.models.notification import NotificationType

    api_params = (ss.filters or {}).get("api")
    if not isinstance(api_params, dict):
        logger.warning(
            "saved_search_alerts: search %s has alerts on but no filters.api — skipping",
            ss.id,
        )
        return False

    token = create_access_token(
        subject=owner.id, role=getattr(owner.role, "value", str(owner.role))
    )
    resp = await client.get(
        "/api/candidates",
        params=build_scan_params(api_params, ss.last_seen_candidate_id),
        headers={"Authorization": f"Bearer {token}"},
    )
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items") or []
    total = int(data.get("total") or 0)
    if not items:
        return False

    # Watermark advances to the highest id on the page. With >100 new matches
    # the stragglers stay above the watermark and roll into the next run.
    max_id = max(int(it["id"]) for it in items)
    # The notification is resurfaced in place for same-day finds, so the
    # headline count is CUMULATIVE since the owner last opened the search —
    # consistent with the unseen badge in the saved-searches menu.
    unseen_total = (ss.unseen_count or 0) + total
    names = ", ".join(_full_name(it) for it in items[:_NAMES_IN_MESSAGE])
    extra = unseen_total - min(len(items), _NAMES_IN_MESSAGE)
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
    ss.last_seen_candidate_id = max(max_id, ss.last_seen_candidate_id or 0)
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

    Returns the number of searches that produced a notification.
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
                    if ss.last_seen_candidate_id is None:
                        # Pre-0129 row toggled on without watermark — anchor at
                        # "now" instead of notifying about the whole base.
                        from app.api.phase4 import _current_candidate_watermark

                        ss.last_seen_candidate_id = await _current_candidate_watermark(
                            db
                        )
                        await db.commit()
                        continue
                    if await _scan_one(client, db, ss, owner):
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
