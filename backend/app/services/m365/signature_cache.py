"""Outlook signature pull + 24h memoization.

Phase 7.7. The user's Outlook signature is appended to every outbound mail
we send via Graph, so emails from NEXUS look identical to emails the user
sends from Outlook desktop / web.

Source of the signature: the body of the user's most recently sent message.
This heuristic beats the alternatives because:
- `/me/mailboxSettings` does NOT include a signature — only auto-reply text.
- The Roaming Signatures API (`/me/mailboxSettings/signatures`) is preview
  and requires an additional `MailboxSettings.Read` scope we haven't
  requested yet.
- Last sent-items footer works for every Outlook flavour (web, desktop,
  iOS, Android) — whatever client the user types in, the signature is
  baked into the rendered body.

Cache: in-memory, keyed by `(user_id, mailbox_upn)`. TTL is
``settings.M365_SIGNATURE_CACHE_TTL_SECONDS`` (default 24h). A negative
result (no signature found, Graph error) is also memoized so a user with
no signature doesn't trigger a Graph fetch on every single send.

Thread safety: the asyncio event loop serializes dict mutations. Two
concurrent fetches for the same key could race and issue two Graph calls,
but the worst case is one wasted call — values eventually converge.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.services.m365.graph_client import GraphClient, GraphRequestError

logger = logging.getLogger(__name__)


_CacheKey = tuple[int, str]
_CacheEntry = tuple[Optional[str], datetime]

# Module-level cache. Negative results are stored as `(None, expires_at)`.
_cache: dict[_CacheKey, _CacheEntry] = {}


# Sigsep markers Outlook injects between body and signature. Different
# client versions render the "-- " separator differently; we try each
# pattern from most to least specific. The signature is everything AFTER
# the last sigsep match (signatures live at the tail of the body, never
# embedded inside quoted threads).
_SIGSEP_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<br\s*/?>\s*--\s*<br\s*/?>", re.IGNORECASE),
    re.compile(r"<p[^>]*>\s*--\s*</p>", re.IGNORECASE),
    re.compile(r"<div[^>]*>\s*--\s*</div>", re.IGNORECASE),
    re.compile(r"\n--\s*\n"),
)

# Defensive cap — a genuine Outlook signature is small (<3 KB). If the
# "tail after sigsep" is larger than this, we assume our heuristic
# misfired and skip injection rather than embed half an email body.
_MAX_SIGNATURE_LENGTH = 8000


def extract_signature(body_html: str) -> Optional[str]:
    """Pull the signature block off the tail of an HTML body.

    Returns the HTML fragment AFTER the last sigsep marker, or None if no
    marker is found. Public for unit tests; production callers go through
    :func:`get_outlook_signature` to benefit from caching.
    """
    if not body_html:
        return None
    for pattern in _SIGSEP_PATTERNS:
        matches = list(pattern.finditer(body_html))
        if matches:
            tail = body_html[matches[-1].end() :].strip()
            if tail and len(tail) <= _MAX_SIGNATURE_LENGTH:
                return tail
    return None


async def get_outlook_signature(
    gc: GraphClient,
    *,
    user_id: int,
    mailbox_upn: str,
) -> Optional[str]:
    """Return the user's signature HTML, or None when unavailable.

    On cache hit (within TTL) the cached value (possibly None) is returned
    without touching Graph. On miss we fetch the last sent message, parse
    its footer, and memoize the result.
    """
    key: _CacheKey = (user_id, mailbox_upn)
    now = datetime.now(timezone.utc)

    entry = _cache.get(key)
    if entry is not None:
        signature, expires_at = entry
        if now < expires_at:
            return signature

    signature = await _fetch_signature_from_sent_items(gc)
    ttl = max(60, int(settings.M365_SIGNATURE_CACHE_TTL_SECONDS))
    _cache[key] = (signature, now + timedelta(seconds=ttl))
    if signature is None:
        logger.debug(
            "signature_cache: no signature for user_id=%s mailbox=%s — caching negative",
            user_id,
            mailbox_upn,
        )
    return signature


async def _fetch_signature_from_sent_items(gc: GraphClient) -> Optional[str]:
    """Call Graph to read the body of the user's most recent sent message."""
    try:
        page = await gc.get(
            "/me/mailFolders/sentitems/messages",
            params={
                "$top": 1,
                "$orderby": "sentDateTime desc",
                "$select": "body",
            },
        )
    except GraphRequestError as exc:
        # Graph failures must never break the send — log and fall back to
        # "no signature". The cache layer above will memoize None.
        logger.warning(
            "signature_cache: Graph %s while fetching sent items — skipping injection",
            exc.status,
        )
        return None
    except Exception:  # noqa: BLE001 — defensive, see docstring
        logger.exception("signature_cache: unexpected error fetching sent items")
        return None

    messages = page.get("value") if isinstance(page, dict) else None
    if not messages:
        return None

    body = messages[0].get("body") or {}
    content = body.get("content") or ""
    content_type = (body.get("contentType") or "").lower()
    if content_type != "html" or not content:
        return None
    return extract_signature(content)


def _clear_cache_for_tests() -> None:
    """Reset the module-level cache. Test-only — never called by prod code."""
    _cache.clear()
