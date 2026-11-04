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
from app.services.calendar_all_day import normalize_all_day
from app.services.calendar_privacy import PRIVATE_EVENT_TITLE, is_private_marker

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
        # Cap DNS resolution itself — a slow/malicious resolver would otherwise
        # hold a thread-pool worker for the OS default (5–30s); the httpx
        # timeout only starts after getaddrinfo returns.
        infos = await asyncio.wait_for(
            asyncio.to_thread(socket.getaddrinfo, host, None),
            timeout=5,
        )
    except asyncio.TimeoutError as exc:
        raise ICalFetchError("host resolution timed out") from exc
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
    skipped_conflict: int = 0
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source_url": self.source_url,
            "events_fetched": self.events_fetched,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped_past": self.skipped_past,
            "skipped_conflict": self.skipped_conflict,
            "errors": self.errors,
            "error_samples": self.error_samples[:20],
        }


def is_all_day_value(v) -> bool:
    """`date`, ale nie `datetime` (który dziedziczy po `date`) = wpis całodniowy."""
    return isinstance(v, date) and not isinstance(v, datetime)


def _to_datetime(v) -> Optional[datetime]:
    """iCal values may be datetime, date, or None; normalize to UTC datetime."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    return None


# Runda 9 (R9-X1-5): ile wydarzeń zapisujemy w jednym commicie.
_COMMIT_BATCH = 200


@dataclass
class _ParsedEvent:
    uid: str
    summary: str
    description: Optional[str]
    location: Optional[str]
    start: datetime
    end: Optional[datetime]
    all_day: bool


def _parse_feed(raw: bytes) -> list[_ParsedEvent | str]:
    """Rozbiera kanał iCal na proste rekordy — CPU, wołane w wątku.

    Element listy to wydarzenie albo opis błędu tego wydarzenia (brak UID,
    brak DTSTART, wyjątek przy odczycie) — kolejność = kolejność VEVENT.
    """
    from icalendar import Calendar  # local import keeps cold-start light

    cal = Calendar.from_ical(raw)
    out: list[_ParsedEvent | str] = []
    for component in cal.walk("VEVENT"):
        try:
            uid = str(component.get("UID") or "").strip()
            if not uid:
                out.append("event missing UID")
                continue

            summary = str(component.get("SUMMARY") or "Spotkanie").strip()[:255]
            description = str(component.get("DESCRIPTION") or "") or None
            location = str(component.get("LOCATION") or "") or None
            # CLASS:PRIVATE/CONFIDENTIAL = sam zajęty termin, bez treści
            # (lustro `sensitivity` z synchronizacji Outlooka, R3-7).
            if is_private_marker(component.get("CLASS")):
                summary = PRIVATE_EVENT_TITLE
                description = None
                location = None

            raw_start = getattr(component.get("DTSTART"), "dt", None)
            dtstart = _to_datetime(raw_start)
            dtend = _to_datetime(getattr(component.get("DTEND"), "dt", None))
            # `DTSTART;VALUE=DATE` (sama data, bez godziny) to wpis całodniowy
            # — urlop, OOO. Bez flagi siatka rysowała go jako blok 00:00–24:00.
            all_day = is_all_day_value(raw_start)
            if all_day and dtstart is not None:
                dtstart, dtend = normalize_all_day(dtstart, dtend)

            if dtstart is None:
                out.append(f"uid={uid}: missing DTSTART")
                continue
            out.append(
                _ParsedEvent(
                    uid=uid,
                    summary=summary,
                    description=description,
                    location=location,
                    start=dtstart,
                    end=dtend,
                    all_day=all_day,
                )
            )
        except Exception as e:  # noqa: BLE001
            out.append(f"event: {type(e).__name__}")
    return out


@dataclass
class _Batch:
    inserted: int = 0
    updated: int = 0
    uids: set[str] = field(default_factory=set)

    def size(self) -> int:
        return self.inserted + self.updated


async def _commit_batch(
    db: AsyncSession, result: ICalImportResult, batch: _Batch, seen_uids: set[str]
) -> None:
    """Zatwierdza paczkę; nieudany commit wycofuje TYLKO tę paczkę z liczników."""
    try:
        await db.commit()
    except Exception as e:  # noqa: BLE001
        await db.rollback()
        result.errors += 1
        result.error_samples.append(f"commit: {type(e).__name__}")
        result.inserted -= batch.inserted
        result.updated -= batch.updated
        seen_uids.difference_update(batch.uids)
    batch.inserted = 0
    batch.updated = 0
    batch.uids = set()


async def import_ical_url(
    db: AsyncSession,
    url: str,
    *,
    since_days: int = 7,
    source_tag: str = "ical",
    creator_id: Optional[int] = None,
) -> ICalImportResult:
    """Fetch iCal feed and upsert events into calendar_events."""
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
    except httpx.HTTPStatusError as e:
        # Treść i traceback HTTPStatusError niosą PEŁNY adres kalendarza
        # („… for url 'https://…/private-…/basic.ics'”), a adres to sekret —
        # do logu (i Sentry) idzie tylko kod HTTP i klasa (runda 6 audytu).
        logger.warning(
            "iCal fetch failed for host=%s: HTTP %s (%s)",
            _mask_host(url),
            e.response.status_code,
            type(e).__name__,
        )
        result.errors += 1
        result.error_samples.append(f"fetch: HTTP {e.response.status_code}")
        return result
    except httpx.HTTPError as e:
        # Pozostałe błędy httpx (np. InvalidURL) też bywają z adresem w treści.
        logger.warning(
            "iCal fetch failed for host=%s (%s)", _mask_host(url), type(e).__name__
        )
        result.errors += 1
        result.error_samples.append("fetch: unexpected error")
        return result
    except Exception:  # noqa: BLE001
        logger.exception("iCal fetch failed for host=%s", _mask_host(url))
        result.errors += 1
        result.error_samples.append("fetch: unexpected error")
        return result

    # Runda 9 (R9-X1-5): parsowanie do 5 MiB i przejście po komponentach to
    # czysty CPU — w wątku, żeby nie zamrażać pętli jedynego procesu uvicorna.
    try:
        parsed = await asyncio.to_thread(_parse_feed, raw)
    except Exception as e:  # noqa: BLE001
        result.errors += 1
        result.error_samples.append(f"parse: {type(e).__name__}")
        return result

    # UIDs inserted during THIS run. Pending rows are invisible to the
    # collision SELECT below, so a feed repeating a UID would otherwise still
    # hit the unique index at commit and lose the whole batch.
    seen_uids: set[str] = set()
    batch = _Batch()

    for item in parsed:
        result.events_fetched += 1
        if isinstance(item, str):
            result.errors += 1
            if len(result.error_samples) < 20:
                result.error_samples.append(item)
            continue
        try:
            # Skip past events older than cutoff
            if item.start < cutoff:
                result.skipped_past += 1
                continue

            # Upsert by (external_source, external_id) — scoped to this
            # creator so two users importing feeds that share a standard UID
            # cannot overwrite each other's events (P0.8 cross-user overwrite).
            existing = await db.scalar(
                select(CalendarEvent).where(
                    CalendarEvent.external_source == source_tag,
                    CalendarEvent.external_id == item.uid,
                    CalendarEvent.created_by == creator_id,
                )
            )
            if existing:
                existing.title = item.summary
                existing.description = item.description
                existing.location = item.location
                existing.start_time = item.start
                existing.end_time = item.end
                existing.all_day = item.all_day
                result.updated += 1
                batch.updated += 1
            else:
                # The DB carries a partial unique index on
                # (external_source, external_id) that does NOT include
                # created_by (ux_calendar_events_external, migration 0010).
                # Inserting a UID another user already imported would raise
                # IntegrityError at commit and roll back the ENTIRE batch,
                # losing every event in this import. Skip and report the
                # collision instead — we must neither overwrite the other
                # user's event (P0.8) nor destroy this user's import.
                if item.uid in seen_uids:
                    result.skipped_conflict += 1
                    continue
                taken = await db.scalar(
                    select(CalendarEvent.id).where(
                        CalendarEvent.external_source == source_tag,
                        CalendarEvent.external_id == item.uid,
                    )
                )
                if taken is not None:
                    result.skipped_conflict += 1
                    continue
                seen_uids.add(item.uid)
                batch.uids.add(item.uid)
                db.add(
                    CalendarEvent(
                        title=item.summary,
                        description=item.description,
                        event_type=EventType.meeting,
                        start_time=item.start,
                        end_time=item.end,
                        all_day=item.all_day,
                        location=item.location,
                        status=EventStatus.scheduled,
                        external_source=source_tag,
                        external_id=item.uid,
                        created_by=creator_id,
                    )
                )
                result.inserted += 1
                batch.inserted += 1
        except Exception as e:  # noqa: BLE001
            result.errors += 1
            if len(result.error_samples) < 20:
                result.error_samples.append(f"event: {type(e).__name__}")
            continue

        # Runda 9 (R9-X1-5): zapis paczkami — jeden flush tysięcy wierszy na
        # końcu trzymał pętlę i transakcję przez cały import.
        if batch.size() >= _COMMIT_BATCH:
            await _commit_batch(db, result, batch, seen_uids)

    await _commit_batch(db, result, batch, seen_uids)
    return result
