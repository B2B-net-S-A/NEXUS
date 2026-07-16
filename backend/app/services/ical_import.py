"""
Phase 7b.6 — iCal URL calendar import.

Practical fallback for full Outlook/Google OAuth sync: users publish their
calendar as a public iCal URL (available in every major calendar app) and
paste that URL into Nexus. We pull events on demand and upsert them.

Strategy:
- Fetch iCal feed via httpx
- Parse with `icalendar`
- For each VEVENT: upsert CalendarEvent by (external_source, external_id=UID)
- Track counts and skip past events older than `since_days`
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_event import CalendarEvent, EventStatus, EventType

logger = logging.getLogger(__name__)

# ── SSRF-safe fetch limits (P0.8) ────────────────────────────────────────────
_MAX_ICAL_BYTES = 5 * 1024 * 1024  # 5 MiB — generous for a calendar feed
_MAX_REDIRECTS = 3
_FETCH_TIMEOUT = 15.0


class ICalFetchError(Exception):
    """Raised when a feed URL is unsafe or cannot be fetched safely.

    The message is deliberately generic and never contains the URL, so it is
    safe to surface to the client and to logs.
    """


def _mask_host(url: str) -> str:
    """Return only the host for display/logging — the full URL is a secret."""
    try:
        return urlsplit(url).hostname or "?"
    except ValueError:
        return "?"


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local  # incl. 169.254.0.0/16 metadata range
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


async def _assert_host_is_public(host: str) -> None:
    """Resolve ``host`` and require EVERY resolved address to be public.

    Blocks loopback / RFC1918 / link-local (cloud metadata) / ULA / reserved,
    for both IPv4 and IPv6. Runs on each redirect hop so a public host cannot
    bounce the request to an internal address.
    """
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except socket.gaierror as exc:
        raise ICalFetchError("host could not be resolved") from exc
    ips = {info[4][0] for info in infos}
    if not ips:
        raise ICalFetchError("host did not resolve")
    for ip in ips:
        if not _is_public_ip(ip):
            raise ICalFetchError("host resolves to a non-public address")


async def _fetch_ical_safely(url: str) -> bytes:
    """Fetch an iCal feed with SSRF protection.

    - HTTPS only.
    - Every hop's host must resolve exclusively to public IPs.
    - Redirects are followed manually and re-validated (bounded count).
    - Response body is capped while streaming.

    Note: a determined attacker could still DNS-rebind between validation and
    the httpx connection (TOCTOU). Closing that fully requires pinning the
    connection to the validated IP; the durable CalendarFeed rewrite (Wave E)
    will address it. This containment blocks the practical redirect/private-host
    SSRF paths.
    """
    current = url
    async with httpx.AsyncClient(
        timeout=_FETCH_TIMEOUT, follow_redirects=False
    ) as client:
        for _ in range(_MAX_REDIRECTS + 1):
            parts = urlsplit(current)
            if parts.scheme != "https":
                raise ICalFetchError("only https feeds are allowed")
            if not parts.hostname:
                raise ICalFetchError("feed URL has no host")
            await _assert_host_is_public(parts.hostname)

            async with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        raise ICalFetchError("redirect without a location")
                    current = urljoin(current, location)
                    continue
                resp.raise_for_status()
                total = 0
                chunks: list[bytes] = []
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > _MAX_ICAL_BYTES:
                        raise ICalFetchError("feed exceeds the size limit")
                    chunks.append(chunk)
                return b"".join(chunks)
    raise ICalFetchError("too many redirects")


@dataclass
class ICalImportResult:
    source_url: str
    events_fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_past: int = 0
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source_url": self.source_url,
            "events_fetched": self.events_fetched,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped_past": self.skipped_past,
            "errors": self.errors,
            "error_samples": self.error_samples[:20],
        }


def _to_datetime(v) -> Optional[datetime]:
    """iCal values may be datetime, date, or None; normalize to UTC datetime."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    return None


async def import_ical_url(
    db: AsyncSession,
    url: str,
    *,
    since_days: int = 7,
    source_tag: str = "ical",
    creator_id: Optional[int] = None,
) -> ICalImportResult:
    """Fetch iCal feed and upsert events into calendar_events."""
    from icalendar import Calendar  # local import keeps cold-start light

    # P0.8: never store or echo the full URL — it is effectively a secret
    # (public iCal URLs grant read access to the whole calendar). Keep only the
    # host for display/logging.
    result = ICalImportResult(source_url=_mask_host(url))
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, since_days))

    try:
        raw = await _fetch_ical_safely(url)
    except ICalFetchError as e:
        # Safe, URL-free message (str(ICalFetchError) has no URL).
        logger.warning("iCal fetch rejected for host=%s: %s", _mask_host(url), e)
        result.errors += 1
        result.error_samples.append(f"fetch: {e}")
        return result
    except Exception:  # noqa: BLE001
        logger.exception("iCal fetch failed for host=%s", _mask_host(url))
        result.errors += 1
        result.error_samples.append("fetch: unexpected error")
        return result

    try:
        cal = Calendar.from_ical(raw)
    except Exception as e:  # noqa: BLE001
        result.errors += 1
        result.error_samples.append(f"parse: {e!r}")
        return result

    for component in cal.walk("VEVENT"):
        result.events_fetched += 1
        try:
            uid = str(component.get("UID") or "").strip()
            if not uid:
                result.errors += 1
                if len(result.error_samples) < 20:
                    result.error_samples.append("event missing UID")
                continue

            summary = str(component.get("SUMMARY") or "Spotkanie").strip()[:255]
            description = str(component.get("DESCRIPTION") or "") or None
            location = str(component.get("LOCATION") or "") or None

            dtstart = _to_datetime(getattr(component.get("DTSTART"), "dt", None))
            dtend = _to_datetime(getattr(component.get("DTEND"), "dt", None))

            if dtstart is None:
                result.errors += 1
                if len(result.error_samples) < 20:
                    result.error_samples.append(f"uid={uid}: missing DTSTART")
                continue

            # Skip past events older than cutoff
            if dtstart < cutoff:
                result.skipped_past += 1
                continue

            # Upsert by (external_source, external_id) — scoped to this
            # creator so two users importing feeds that share a standard UID
            # cannot overwrite each other's events (P0.8 cross-user overwrite).
            existing = await db.scalar(
                select(CalendarEvent).where(
                    CalendarEvent.external_source == source_tag,
                    CalendarEvent.external_id == uid,
                    CalendarEvent.created_by == creator_id,
                )
            )
            if existing:
                existing.title = summary
                existing.description = description
                existing.location = location
                existing.start_time = dtstart
                existing.end_time = dtend
                result.updated += 1
            else:
                ev = CalendarEvent(
                    title=summary,
                    description=description,
                    event_type=EventType.meeting,
                    start_time=dtstart,
                    end_time=dtend,
                    all_day=False,
                    location=location,
                    status=EventStatus.scheduled,
                    external_source=source_tag,
                    external_id=uid,
                    created_by=creator_id,
                )
                db.add(ev)
                result.inserted += 1
        except Exception as e:  # noqa: BLE001
            result.errors += 1
            if len(result.error_samples) < 20:
                result.error_samples.append(f"event: {e!r}")

    try:
        await db.commit()
    except Exception as e:  # noqa: BLE001
        await db.rollback()
        result.errors += 1
        result.error_samples.append(f"commit: {e!r}")

    return result
