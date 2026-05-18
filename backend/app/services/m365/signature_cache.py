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

Marker strategy (extract_signature). The Outlook ecosystem ships at least
three signature formats — we try each in turn:

1. **Element-id markers** (Outlook mobile/desktop/OWA). Modern clients wrap
   the signature in a div with a recognisable id:
   ``<div id="ms-outlook-mobile-signature">``,
   ``<div id="Signature">``,
   ``<div id="x_Signature">`` (OWA prefixes ids with ``x_`` when quoting).
   For these the matched ``<div>`` IS the start of the signature, so the
   extracted tail INCLUDES the wrapper element.
2. **Classic plaintext sigsep** (``-- ``) rendered as HTML
   (``<br>--<br>``, ``<p>--</p>``, ``<div>--</div>`` or literal ``\\n--\\n``
   in a wrapped plaintext mail). The matched text IS the separator, so the
   extracted tail starts AFTER it.

When multiple matches exist, the **last** one wins — signatures live at the
tail of the body, and an earlier "--" inside a quoted reply is not the
signature.

Cache: in-memory, keyed by ``(user_id, mailbox_upn)``. TTL is
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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.services.m365.graph_client import GraphClient, GraphRequestError

logger = logging.getLogger(__name__)


_CacheKey = tuple[int, str]
_CacheEntry = tuple[Optional[str], datetime]

# Module-level cache. Negative results are stored as `(None, expires_at)`.
_cache: dict[_CacheKey, _CacheEntry] = {}


@dataclass(frozen=True)
class _SigsepMarker:
    """A signature boundary marker plus how to slice around it.

    ``include_match=True``: the matched span IS the start of the signature
    (e.g. the opening ``<div id="...">``). Extract from ``match.start()``.

    ``include_match=False``: the matched span is a SEPARATOR between body
    and signature (e.g. ``<br>--<br>``). Extract from ``match.end()``.
    """

    pattern: re.Pattern[str]
    include_match: bool


# Order matters: try the most specific (id-based) markers first so a body
# that happens to contain both "-- " inside a quoted reply AND a real id
# wrapper still extracts the id-wrapped signature.
_SIGSEP_MARKERS: tuple[_SigsepMarker, ...] = (
    # Outlook mobile (iOS + Android) — signature always lands in this div.
    _SigsepMarker(
        re.compile(
            r"""<div\b[^>]*\bid\s*=\s*["']?ms-outlook-mobile-signature["']?""",
            re.IGNORECASE,
        ),
        include_match=True,
    ),
    # Outlook desktop / OWA — modern compose wraps in <div id="Signature">.
    # The leading ``x_`` form appears when an OWA-sent mail is later quoted
    # by the same OWA client (it namespaces nested ids).
    _SigsepMarker(
        re.compile(
            r"""<div\b[^>]*\bid\s*=\s*["']?(?:x_)?Signature["']?""",
            re.IGNORECASE,
        ),
        include_match=True,
    ),
    # Classic plaintext sigsep ("-- " on its own line), HTML-rendered.
    _SigsepMarker(
        re.compile(r"<br\s*/?>\s*--\s*<br\s*/?>", re.IGNORECASE),
        include_match=False,
    ),
    _SigsepMarker(
        re.compile(r"<p[^>]*>\s*--\s*</p>", re.IGNORECASE),
        include_match=False,
    ),
    _SigsepMarker(
        re.compile(r"<div[^>]*>\s*--\s*</div>", re.IGNORECASE),
        include_match=False,
    ),
    _SigsepMarker(re.compile(r"\n--\s*\n"), include_match=False),
)

# Defensive cap. Real Outlook signatures with logo tables top out around
# 6-8 KB; 12 KB leaves headroom for branded enterprise templates without
# inviting half-body misfires.
_MAX_SIGNATURE_LENGTH = 12000


def extract_signature(body_html: str) -> Optional[str]:
    """Pull the signature block off an HTML body.

    Returns the HTML fragment from the last matching marker (using the
    marker's slicing rule), or ``None`` if no marker is found. Public for
    unit tests; production callers go through :func:`get_outlook_signature`
    to benefit from caching.
    """
    if not body_html:
        return None
    for marker in _SIGSEP_MARKERS:
        matches = list(marker.pattern.finditer(body_html))
        if not matches:
            continue
        last = matches[-1]
        pos = last.start() if marker.include_match else last.end()
        tail = body_html[pos:].strip()
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


# How many recent sent messages to scan when probing for a signature.
# Real users intersperse signed mails with auto-generated ones (Teams
# meeting invites, calendar replies, "OK" one-liners) — so the literal
# "last sent" often has no signature even when the user does have one
# configured. Walking 10 back is enough to find a typed-out message in
# practice while keeping the Graph call to a single page.
_SENT_ITEMS_PROBE_DEPTH = 10


async def _fetch_signature_from_sent_items(gc: GraphClient) -> Optional[str]:
    """Find the user's signature by scanning recent sent messages.

    Strategy: fetch the last ``_SENT_ITEMS_PROBE_DEPTH`` sent messages in
    one Graph call, then return the FIRST one whose body yields a sigsep
    match. This survives Teams invites, auto-replies, and other body
    formats Outlook generates without a user signature attached.
    """
    try:
        page = await gc.get(
            "/me/mailFolders/sentitems/messages",
            params={
                "$top": _SENT_ITEMS_PROBE_DEPTH,
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

    for msg in messages:
        body = msg.get("body") or {}
        content_type = (body.get("contentType") or "").lower()
        content = body.get("content") or ""
        if content_type != "html" or not content:
            continue
        signature = extract_signature(content)
        if signature is not None:
            return signature
    return None


def _clear_cache_for_tests() -> None:
    """Reset the module-level cache. Test-only — never called by prod code."""
    _cache.clear()
