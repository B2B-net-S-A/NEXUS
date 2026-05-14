"""OneDrive helpers — currently used to locate Teams meeting recordings.

When a Teams meeting ends, Microsoft Teams auto-saves the recording to the
organizer's OneDrive under ``/Recordings/<title>-<timestamp>.mp4``. The file
is owned by the organizer and gets a Stream-style sharing link. We rely on
``GET /me/drive/root/search(q=...)`` (delegated ``Files.Read``) so we don't
need the heavier ``OnlineMeetingRecording.Read.All`` application permission.

The match heuristic is intentionally conservative:

1. Filter by content type / suffix to ``.mp4`` only — OneDrive search returns
   plenty of false positives (e.g. notes named "Recording overview").
2. Require ``createdDateTime`` to fall inside a window anchored on the event
   end (default: ``end - 30min .. end + 4h``). Teams typically publishes a
   recording within an hour, but we leave headroom for slow tenants.
3. If the meeting ID can be extracted from ``online_meeting_url``, prefer
   files whose name contains a fragment of it. Otherwise, take the closest
   match by ``createdDateTime`` to the event end.

This module returns the *sharing URL* (``webUrl``) — that's the link a
recruiter can paste in a candidate profile and re-open in a browser. We
deliberately do not download the recording (transcripts may be GBs).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.services.m365.graph_client import GraphClient, GraphRequestError

logger = logging.getLogger(__name__)


# Time window around the event end where we accept a recording. Teams almost
# always publishes within ~1h but we leave a generous tail for slow tenants
# and the 6h discovery cadence we run in the background loop.
_WINDOW_BEFORE = timedelta(minutes=30)
_WINDOW_AFTER = timedelta(hours=4)

# OneDrive search returns 200 results per page; recordings are sparse enough
# that 50 is plenty for a single event scan and keeps the response compact.
_SEARCH_PAGE_SIZE = 50

# Conservative content-type / extension allowlist. Teams used to publish
# ``video/mp4`` exclusively; some tenants now ship ``application/octet-stream``
# with the ``.mp4`` extension, so we accept either.
_RECORDING_CONTENT_TYPES: frozenset[str] = frozenset(
    {"video/mp4", "application/octet-stream"}
)
_RECORDING_SUFFIX = ".mp4"

# Teams meeting URLs look like:
#   https://teams.microsoft.com/l/meetup-join/19%3ameeting_<base64>%40thread.v2/...
# We extract the ``meeting_<base64>`` token so we can prefer files whose name
# contains a fragment of it (Teams sometimes embeds it in the recording
# filename, e.g. ``Recording-<title>-meeting_<base64>.mp4``).
_MEETING_ID_RE = re.compile(r"meeting_([A-Za-z0-9+/_=%-]+)")


@dataclass(frozen=True)
class _Candidate:
    """One OneDrive item that *might* be the meeting recording."""

    name: str
    web_url: str
    created_at: datetime
    content_type: str


def extract_meeting_id_fragment(online_meeting_url: Optional[str]) -> Optional[str]:
    """Pull the ``meeting_<token>`` fragment out of a Teams join URL.

    Returns at most the first 12 characters — long enough to be specific to
    a single meeting in practice but short enough to survive URL/filename
    encoding round-trips and to avoid string-equality misses on edge cases
    where Teams appends a region suffix.
    """
    if not online_meeting_url:
        return None
    match = _MEETING_ID_RE.search(online_meeting_url)
    if not match:
        return None
    token = match.group(1)
    return token[:12] if token else None


def _parse_created_at(raw: object) -> Optional[datetime]:
    """Parse Graph's ``createdDateTime`` (RFC3339 with ``Z``)."""
    if not isinstance(raw, str) or not raw:
        return None
    iso = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_recording_candidate(item: dict, *, window_start: datetime,
                            window_end: datetime) -> Optional[_Candidate]:
    """Apply the cheap filters: filename, content type, time window."""
    name = (item.get("name") or "").strip()
    if not name.lower().endswith(_RECORDING_SUFFIX):
        return None

    web_url = item.get("webUrl")
    if not isinstance(web_url, str) or not web_url:
        return None

    file_info = item.get("file") or {}
    content_type = ""
    if isinstance(file_info, dict):
        content_type = (file_info.get("mimeType") or "").strip().lower()
    if content_type and content_type not in _RECORDING_CONTENT_TYPES:
        return None

    created_at = _parse_created_at(item.get("createdDateTime"))
    if created_at is None:
        return None
    if not (window_start <= created_at <= window_end):
        return None

    return _Candidate(
        name=name,
        web_url=web_url,
        created_at=created_at,
        content_type=content_type or "video/mp4",
    )


def _pick_best_match(
    candidates: list[_Candidate],
    *,
    event_end_at: datetime,
    meeting_id_fragment: Optional[str],
) -> Optional[_Candidate]:
    """Prefer name match on the meeting ID; otherwise closest by time."""
    if not candidates:
        return None
    if meeting_id_fragment:
        fragment = meeting_id_fragment.lower()
        with_id = [c for c in candidates if fragment in c.name.lower()]
        if with_id:
            # Multiple hits → still take the closest in time so a leftover
            # file from a re-recorded meeting doesn't beat the real one.
            return min(with_id, key=lambda c: abs(c.created_at - event_end_at))
    return min(candidates, key=lambda c: abs(c.created_at - event_end_at))


async def find_meeting_recording(
    gc: GraphClient,
    *,
    online_meeting_url: Optional[str],
    event_end_at: datetime,
) -> Optional[str]:
    """Return a OneDrive sharing URL for the meeting recording, if any.

    `event_end_at` MUST be timezone-aware (we normalise to UTC internally).
    `online_meeting_url` is optional — if provided we use it to disambiguate
    multiple ``.mp4`` files inside the time window; if omitted we just take
    the temporally-closest hit.

    Returns ``None`` when:
    - ``event_end_at`` is naive (programmer error, fail closed).
    - The search call errors out (Graph 4xx/5xx is logged and swallowed;
      the loop will retry on the next pass).
    - No file in the time window matches the conservative heuristic.
    """
    if event_end_at.tzinfo is None:
        logger.warning("find_meeting_recording: event_end_at must be tz-aware")
        return None

    end_utc = event_end_at.astimezone(timezone.utc)
    window_start = end_utc - _WINDOW_BEFORE
    window_end = end_utc + _WINDOW_AFTER

    # Graph search is wildcard-ish; "Recording" matches the default Teams
    # filename prefix without being case-sensitive. We sort newest-first so
    # the small page size is enough even when the user has months of files.
    params = {
        "$top": _SEARCH_PAGE_SIZE,
        "$orderby": "createdDateTime desc",
        "$select": "id,name,webUrl,createdDateTime,file",
    }
    try:
        payload = await gc.get("/me/drive/root/search(q='Recording')", params=params)
    except GraphRequestError as exc:
        # 403 typically means missing Files.Read on this tenant; 404 means
        # OneDrive is not provisioned for the organizer. Either way it's the
        # admin's call — log and back off.
        logger.warning(
            "OneDrive recording search failed: status=%s body=%r", exc.status, exc.body
        )
        return None

    items = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None

    candidates: list[_Candidate] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        candidate = _is_recording_candidate(
            raw, window_start=window_start, window_end=window_end
        )
        if candidate is not None:
            candidates.append(candidate)

    fragment = extract_meeting_id_fragment(online_meeting_url)
    best = _pick_best_match(
        candidates, event_end_at=end_utc, meeting_id_fragment=fragment
    )
    if best is None:
        return None
    return best.web_url
