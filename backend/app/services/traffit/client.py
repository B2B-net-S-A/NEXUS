"""Traffit API client — OAuth2 client_credentials + paginated GET with throttling.

Discovery (docs/traffit-discovery.md):
- Tenant URL: https://<tenant>.traffit.com (no www).
- Token: POST /oauth2/token, expires_in=2592000s (30 days).
- Pagination headers: X-Request-Page-Size / X-Request-Current-Page.
- Response headers: X-Result-Total-Count etc.
- 301 redirects on some endpoints (talents, workflows, sources, provisions) — follow.

Throttling: configurable RPS (default 5) via asyncio.Semaphore-style sleep.
Backoff: exponential on 429/5xx (max 3 retries).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class TraffitConfig:
    tenant: str
    client_id: str
    client_secret: str
    throttle_rps: float = 5.0
    timeout_s: float = 30.0
    connect_timeout_s: float = 10.0
    read_timeout_s: float = 180.0
    max_retries: int = 3

    @property
    def base_url(self) -> str:
        return f"https://{self.tenant}.traffit.com"

    @property
    def api_base(self) -> str:
        return f"{self.base_url}/api/integration/v2"

    @property
    def token_url(self) -> str:
        return f"{self.base_url}/oauth2/token"

    @classmethod
    def from_env(cls) -> "TraffitConfig":
        tenant = os.environ.get("TRAFFIT_TENANT")
        client_id = os.environ.get("TRAFFIT_CLIENT_ID")
        client_secret = os.environ.get("TRAFFIT_CLIENT_SECRET")
        if not tenant or not client_id or not client_secret:
            raise RuntimeError(
                "TRAFFIT_TENANT, TRAFFIT_CLIENT_ID, TRAFFIT_CLIENT_SECRET "
                "must be set in environment"
            )
        throttle = float(os.environ.get("TRAFFIT_THROTTLE_RPS", "5"))
        read_timeout = float(os.environ.get("TRAFFIT_READ_TIMEOUT_S", "180"))
        connect_timeout = float(os.environ.get("TRAFFIT_CONNECT_TIMEOUT_S", "10"))
        return cls(
            tenant=tenant,
            client_id=client_id,
            client_secret=client_secret,
            throttle_rps=throttle,
            connect_timeout_s=connect_timeout,
            read_timeout_s=read_timeout,
        )


# All scopes from the API key (per prompt). Token requests can space-join them.
ALL_SCOPES = (
    "advert advert_publish crm_activity crm_person dictionary file form "
    "message provision source talent user webhook client recruitment employee "
    "workflow"
)


class TraffitClient:
    """Async client. Use as `async with TraffitClient(config) as c:`."""

    def __init__(self, config: TraffitConfig, scope: str = ALL_SCOPES) -> None:
        self.config = config
        self.scope = scope
        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._http: Optional[httpx.AsyncClient] = None
        self._min_interval_s = (
            1.0 / config.throttle_rps if config.throttle_rps > 0 else 0.0
        )
        self._last_call_at: Optional[datetime] = None
        self._call_lock = asyncio.Lock()

    async def __aenter__(self) -> "TraffitClient":
        # Split timeout: a generous read cap (default 180s) lets a large
        # catch-up page of /employees/activities return without a ReadTimeout,
        # while connect stays tight (10s) so a genuinely dead endpoint still
        # fails fast. Was a bare 30s total, which throttled the activities feed
        # into a permanent `degraded`.
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(
                self.config.timeout_s,
                connect=self.config.connect_timeout_s,
                read=self.config.read_timeout_s,
            ),
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ── Auth ────────────────────────────────────────────────────────────────

    async def _ensure_token(self) -> str:
        now = datetime.now(timezone.utc)
        if (
            self._token is not None
            and self._token_expires_at is not None
            and now < self._token_expires_at - timedelta(minutes=5)
        ):
            return self._token

        assert self._http is not None
        body = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "grant_type": "client_credentials",
            "scope": self.scope,
        }
        resp = await self._http.post(
            self.config.token_url,
            json=body,
            headers={"Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Token request failed: HTTP {resp.status_code} {resp.text[:200]}"
            )
        data = resp.json()
        self._token = data["access_token"]
        expires_in = int(data.get("expires_in", 86400))
        self._token_expires_at = now + timedelta(seconds=expires_in)
        logger.info(
            "Traffit token refreshed (expires_in=%ds, scope=%s)",
            expires_in,
            data.get("scope"),
        )
        # _token is set above
        assert self._token is not None
        return self._token

    # ── Throttling ──────────────────────────────────────────────────────────

    async def _throttle(self) -> None:
        if self._min_interval_s <= 0:
            return
        async with self._call_lock:
            now = datetime.now(timezone.utc)
            if self._last_call_at is not None:
                elapsed = (now - self._last_call_at).total_seconds()
                wait = self._min_interval_s - elapsed
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_call_at = datetime.now(timezone.utc)

    # ── Low-level GET with retries ──────────────────────────────────────────

    # Traffit hard cap (some endpoints return HTTP 400 above this, others
    # silently cap and report actual via X-Result-Page-Size).
    MAX_PAGE_SIZE = 100

    async def _get_raw(
        self,
        path: str,
        *,
        page: int = 1,
        page_size: int = 100,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> httpx.Response:
        token = await self._ensure_token()
        assert self._http is not None

        effective_size = min(page_size, self.MAX_PAGE_SIZE)
        url = f"{self.config.api_base}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Request-Page-Size": str(effective_size),
            "X-Request-Current-Page": str(page),
        }
        if extra_headers:
            headers.update(extra_headers)

        for attempt in range(self.config.max_retries + 1):
            await self._throttle()
            try:
                resp = await self._http.get(url, headers=headers)
            except httpx.TransportError as exc:
                # Transport-level failure (ReadTimeout / ConnectTimeout /
                # network / protocol) — never surfaced as a `resp`, so it
                # bypassed the status-based retry below and aborted the whole
                # phase. Retry with the same backoff, then re-raise. Mirrors
                # proxycurl/client.py and m365/graph_client.py.
                if attempt < self.config.max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "Traffit %s transport error %r, backoff %ds (attempt %d/%d)",
                        path,
                        exc,
                        wait,
                        attempt + 1,
                        self.config.max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
            if resp.status_code == 401 and attempt == 0:
                # Token may have been invalidated mid-flight — force refresh.
                self._token = None
                token = await self._ensure_token()
                headers["Authorization"] = f"Bearer {token}"
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.config.max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "Traffit %s HTTP %d, backoff %ds (attempt %d/%d)",
                        path,
                        resp.status_code,
                        wait,
                        attempt + 1,
                        self.config.max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue
            return resp
        # Loop exhausted — return last response (caller checks status)
        return resp

    # ── High-level paginated iteration ──────────────────────────────────────

    async def total_count(self, path: str) -> int:
        """Probe X-Result-Total-Count via 1-page-size HEAD-like GET."""
        resp = await self._get_raw(path, page=1, page_size=1)
        if resp.status_code != 200:
            raise RuntimeError(
                f"GET {path} failed: HTTP {resp.status_code} {resp.text[:200]}"
            )
        return int(resp.headers.get("X-Result-Total-Count", "0"))

    async def get_paginated(
        self,
        path: str,
        *,
        page_size: int = 100,
        skip_on_5xx: bool = False,
        filter_: Optional[dict] = None,
        fallback_on_filter_rejection: bool = True,
    ) -> AsyncIterator[dict]:
        """Yield each item across all pages. Sorts on `id ASC` for stability.

        skip_on_5xx: when True, log a 5xx page and continue past it instead of
            raising. Useful for /sources/ on b2bnetwork tenant which has random
            HTTP 500s on specific pages — losing the failed page is preferable
            to aborting the whole import.

        filter_: optional Traffit ``X-Request-Filter`` dict, e.g.
            ``{"updated_at": {"value": "2026-06-15", "comparison": ">="}}``.
            Used for incremental (daily) delta syncs. If the tenant rejects the
            filter header with HTTP 400, we log and fall back to a full scan —
            the importer's upserts are idempotent, so a full scan is always safe,
            just slower.

        fallback_on_filter_rejection: preserves the legacy importer's full-scan
            fallback by default.  Strict near-real-time consumers must pass
            ``False``: a rejected filter then raises without ever issuing an
            unfiltered request.  This prevents a lightweight poll from silently
            turning into a historical full scan.
        """
        # The filter may be dropped mid-flight if the server rejects it (400).
        active_filter = filter_
        page = 1
        # If we know the total page count from page=1, use it; otherwise we
        # rely on len(items) < page_size to stop. With skip_on_5xx the first
        # page might fail, so we probe total_pages via total_count for safety.
        total_pages_known: Optional[int] = None
        if skip_on_5xx:
            try:
                total = await self.total_count(path)
                if total > 0:
                    total_pages_known = (total + page_size - 1) // page_size
            except Exception:  # noqa: BLE001
                total_pages_known = None

        while True:
            extra_headers = {"X-Request-Sort": json.dumps({"id": "ASC"})}
            if active_filter is not None:
                extra_headers["X-Request-Filter"] = json.dumps(active_filter)
            resp = await self._get_raw(
                path,
                page=page,
                page_size=page_size,
                extra_headers=extra_headers,
            )
            # Tenant rejected the delta filter — degrade to a full scan. Safe
            # because every importer upsert is ON CONFLICT idempotent.
            if (
                resp.status_code == 400
                and active_filter is not None
                and page == 1
                and fallback_on_filter_rejection
            ):
                logger.warning(
                    "GET %s rejected X-Request-Filter (HTTP 400) — "
                    "falling back to full scan without filter",
                    path,
                )
                active_filter = None
                continue
            if resp.status_code != 200:
                if skip_on_5xx and 500 <= resp.status_code < 600:
                    logger.warning(
                        "GET %s page=%d HTTP %d — skipping page",
                        path,
                        page,
                        resp.status_code,
                    )
                    if total_pages_known and page >= total_pages_known:
                        return
                    page += 1
                    continue
                raise RuntimeError(
                    f"GET {path} page={page}: HTTP {resp.status_code} {resp.text[:200]}"
                )
            try:
                items = resp.json()
            except (json.JSONDecodeError, ValueError) as exc:
                message = f"Bad JSON from {path} page={page}"
                if not fallback_on_filter_rejection:
                    raise RuntimeError(message) from exc
                logger.error("%s", message)
                return
            if not isinstance(items, list):
                message = f"Expected list, got {type(items)} from {path} page={page}"
                if not fallback_on_filter_rejection:
                    raise RuntimeError(message)
                logger.error("%s", message)
                return
            if not items:
                return
            for item in items:
                yield item
            total_pages = int(resp.headers.get("X-Result-Total-Pages", "0"))
            if total_pages:
                # Total-pages header is authoritative when present.
                # Some Traffit endpoints (/crm_persons/) return non-uniform
                # page sizes (e.g. 99 items on intermediate pages of 100),
                # so len(items) is unreliable as a stop signal.
                if page >= total_pages:
                    return
            else:
                # Fallback when total-pages absent: short page = last page.
                actual_page_size = int(
                    resp.headers.get("X-Result-Page-Size", page_size)
                )
                if len(items) < actual_page_size:
                    return
            page += 1
