"""Async HTTP client for Proxycurl's LinkedIn profile endpoint.

Mirrors the retry/rate-limit shape of `app.services.m365.graph_client`:
- Class-level semaphore throttles concurrent Proxycurl calls process-wide.
- 429 / 503 → honor Retry-After (capped 60s) and retry.
- Network errors → retry 2× with jitter.
- 404 → `ProfileNotFound` (non-retriable; profile private / removed).

Static API key lives in `settings.PROXYCURL_API_KEY` — no per-user OAuth.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

PROXYCURL_BASE = "https://nubela.co/proxycurl/api/v2/linkedin"
_CONCURRENCY = 4
_MAX_RETRIES_NETWORK = 2
_RETRY_AFTER_CAP_SECONDS = 60

_LINKEDIN_SLUG_RE = re.compile(r"^[\w\-%._]+$", re.IGNORECASE)


class ProxycurlError(RuntimeError):
    """Non-retriable Proxycurl response (5xx that outlasted retries, 4xx !=404)."""

    def __init__(self, status: int, body: Any) -> None:
        super().__init__(f"Proxycurl {status}: {body!r}")
        self.status = status
        self.body = body


class ProfileNotFound(ProxycurlError):
    """Proxycurl returned 404 — LinkedIn profile is private or removed."""

    def __init__(self, url: str) -> None:
        super().__init__(404, f"profile not found: {url}")
        self.url = url


@dataclass(frozen=True)
class ProxycurlProfile:
    """Subset of Proxycurl profile payload we care about.

    `raw` keeps the full dict for downstream consumers (persisted to
    `candidate_linkedin_snapshots.profile_json`). Derived fields are the
    top of `experiences` where `ends_at is None` (= current position).
    """

    raw: dict = field(default_factory=dict)
    current_company: Optional[str] = None
    current_title: Optional[str] = None
    current_started_at: Optional[date] = None


class ProxycurlClient:
    """Process-wide throttled Proxycurl client.

    Use as async context manager — it shares one `httpx.AsyncClient` for the
    lifetime of the call, closed on exit.
    """

    _semaphore: asyncio.Semaphore = asyncio.Semaphore(_CONCURRENCY)

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key or settings.PROXYCURL_API_KEY
        if not self._api_key:
            raise ProxycurlError(0, "PROXYCURL_API_KEY is not configured")
        self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "ProxycurlClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    async def fetch_profile(self, linkedin_url: str) -> ProxycurlProfile:
        """Fetch a LinkedIn profile via Proxycurl's /v2/linkedin endpoint.

        `use_cache=if-recent` uses Proxycurl's cache if ≤ 29 days old
        (~$0.01 per cached call vs ~$0.04 live). Good enough for our 7-day
        staleness cutoff.
        """

        normalized = normalize_linkedin_url(linkedin_url)
        if normalized is None:
            raise ProxycurlError(0, f"invalid linkedin_url: {linkedin_url!r}")

        headers = {"Authorization": f"Bearer {self._api_key}"}
        params = {"url": normalized, "use_cache": "if-recent"}

        async with ProxycurlClient._semaphore:
            network_tries = 0
            while True:
                try:
                    resp = await self._client.get(
                        PROXYCURL_BASE, params=params, headers=headers
                    )
                except (httpx.ConnectError, httpx.ReadTimeout, httpx.ReadError):
                    network_tries += 1
                    if network_tries > _MAX_RETRIES_NETWORK:
                        raise
                    await asyncio.sleep(1.0 + random.random() * 1.5)
                    continue

                # 404 → profile not found / private — non-retriable.
                if resp.status_code == 404:
                    raise ProfileNotFound(normalized)

                # 429 / 503 → honor Retry-After (clamped), then retry.
                if resp.status_code in (429, 503):
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                    sleep_s = min(retry_after, _RETRY_AFTER_CAP_SECONDS)
                    logger.warning(
                        "Proxycurl throttled %s — sleeping %ds for %s",
                        resp.status_code,
                        sleep_s,
                        normalized,
                    )
                    await asyncio.sleep(sleep_s)
                    continue

                if resp.status_code >= 400:
                    body: Any
                    try:
                        body = resp.json()
                    except Exception:  # noqa: BLE001
                        body = resp.text
                    raise ProxycurlError(resp.status_code, body)

                payload = resp.json() if resp.content else {}
                return _build_profile(payload)


def normalize_linkedin_url(url: Optional[str]) -> Optional[str]:
    """Canonicalize a LinkedIn profile URL.

    Accepts common user variants ("linkedin.com/in/jane-doe",
    "https://pl.linkedin.com/in/jane-doe/?foo=bar"). Returns canonical
    "https://linkedin.com/in/<slug>" or None if the input is malformed.
    """

    if not url:
        return None
    raw = url.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parsed = urlparse(raw)
    except ValueError:
        return None

    host = (parsed.netloc or "").lower()
    # Strip regional prefix (pl., www., etc.) — Proxycurl accepts the
    # canonical linkedin.com form.
    if not host.endswith("linkedin.com"):
        return None

    path = parsed.path or ""
    # Match "/in/<slug>" or "/in/<slug>/". Reject other path shapes
    # (company pages, job listings, etc.).
    parts = [p for p in path.split("/") if p]
    if len(parts) < 2 or parts[0].lower() != "in":
        return None
    slug = parts[1]
    if not _LINKEDIN_SLUG_RE.match(slug):
        return None
    return f"https://linkedin.com/in/{slug}"


def _build_profile(payload: dict) -> ProxycurlProfile:
    """Extract current employment from a Proxycurl v2 response.

    Proxycurl structures experience as `experiences: [{company, title,
    starts_at: {day, month, year}, ends_at: null|{...}, ...}, ...]`.
    The "current" position is the first entry where `ends_at is None`.
    If every entry has an end date (rare — fully retired profile), current
    employer is None and downstream diff treats the snapshot as
    "no current employment".
    """

    experiences = payload.get("experiences") or []
    current_company: Optional[str] = None
    current_title: Optional[str] = None
    current_started_at: Optional[date] = None
    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        if exp.get("ends_at") is None:
            company = (exp.get("company") or "").strip() or None
            title = (exp.get("title") or "").strip() or None
            current_company = company
            current_title = title
            current_started_at = _parse_proxycurl_date(exp.get("starts_at"))
            break

    return ProxycurlProfile(
        raw=payload,
        current_company=current_company,
        current_title=current_title,
        current_started_at=current_started_at,
    )


def _parse_proxycurl_date(part: Optional[dict]) -> Optional[date]:
    """Proxycurl dates come as {day, month, year}, sometimes partial.

    Missing day/month default to 1 so the start can still be compared. If
    year is absent or non-integer, return None.
    """

    if not isinstance(part, dict):
        return None
    year = part.get("year")
    if not isinstance(year, int):
        return None
    month = part.get("month") if isinstance(part.get("month"), int) else 1
    day = part.get("day") if isinstance(part.get("day"), int) else 1
    try:
        return date(year, month or 1, day or 1)
    except ValueError:
        return None


def _parse_retry_after(header: Optional[str]) -> float:
    if not header:
        return 2.0
    try:
        return float(header)
    except (TypeError, ValueError):
        pass
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(header)
        if dt is None:
            return 2.0
        delta = (dt - datetime.utcnow()).total_seconds()
        return max(0.5, delta)
    except Exception:  # noqa: BLE001
        return 2.0
