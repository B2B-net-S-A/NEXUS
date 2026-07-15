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
import email.utils
import json
import logging
import os
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Mapping, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)


class TraffitAPIError(RuntimeError):
    """Structured error raised by high-level Traffit API calls.

    Workers use ``retryable`` and ``retry_after_s`` to distinguish transient
    transport/rate-limit failures from validation errors which require an
    administrator decision.  The response body is deliberately truncated so
    candidate data cannot accidentally flood logs or error tracking.
    """

    def __init__(
        self,
        method: str,
        path: str,
        status_code: int,
        body: str = "",
        *,
        retry_after_s: Optional[float] = None,
    ) -> None:
        self.method = method.upper()
        self.path = path
        self.status_code = status_code
        self.body = body[:500]
        self.retry_after_s = retry_after_s
        self.retryable = status_code == 429 or status_code >= 500
        super().__init__(
            f"{self.method} {path} failed: HTTP {status_code} {self.body[:200]}"
        )


class TraffitIncompletePageError(RuntimeError):
    """A page could not be proven complete, so a cursor must not advance."""


@dataclass
class TraffitConfig:
    tenant: str
    client_id: str
    client_secret: str
    throttle_rps: float = 5.0
    timeout_s: float = 30.0
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
        return cls(
            tenant=tenant,
            client_id=client_id,
            client_secret=client_secret,
            throttle_rps=throttle,
        )


# All scopes from the API key (per prompt). Token requests can space-join them.
ALL_SCOPES = (
    "advert advert_publish crm_activity crm_person dictionary file form "
    "message provision source talent user webhook client recruitment employee "
    "workflow"
)

INTEGRATION_DEFAULT_SCOPES = (
    "employee recruitment workflow webhook file dictionary source user crm_activity"
)


def integration_scopes_from_env() -> str:
    """Scopes for the new worker; deliberately narrower than legacy import."""
    configured = os.environ.get("TRAFFIT_INTEGRATION_SCOPES", "").strip()
    return configured or INTEGRATION_DEFAULT_SCOPES


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
        self._http = httpx.AsyncClient(
            timeout=self.config.timeout_s,
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

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
        """Parse Retry-After (seconds or HTTP date), clamped to a sane range."""
        raw = response.headers.get("Retry-After")
        if not raw:
            return None
        try:
            value = float(raw)
        except ValueError:
            try:
                retry_at = email.utils.parsedate_to_datetime(raw)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                value = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                return None
        # A bad upstream value must not stall a worker for hours.
        return max(0.0, min(value, 300.0))

    async def _request_raw(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Any = None,
        data: Any = None,
        files: Any = None,
        extra_headers: Optional[Mapping[str, str]] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        retry_non_idempotent: bool = False,
    ) -> httpx.Response:
        """Issue an authenticated request with shared throttle and retries.

        This is intentionally response-oriented: several Traffit write
        endpoints return ``204 No Content`` while others return an entity or a
        list.  Higher layers decide which status/body shape is expected.
        """
        method = method.upper()
        token = await self._ensure_token()
        assert self._http is not None

        url = f"{self.config.api_base}{path}"
        headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
        if files is None:
            headers["Content-Type"] = "application/json"
        if page is not None:
            headers["X-Request-Current-Page"] = str(page)
        if page_size is not None:
            headers["X-Request-Page-Size"] = str(
                min(page_size, self.MAX_PAGE_SIZE)
            )
        if extra_headers:
            headers.update(extra_headers)

        response: Optional[httpx.Response] = None
        retry_safe = method in {"GET", "HEAD", "OPTIONS"} or retry_non_idempotent
        for attempt in range(self.config.max_retries + 1):
            await self._throttle()
            try:
                response = await self._http.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    data=data,
                    files=files,
                    headers=headers,
                )
            except (httpx.TimeoutException, httpx.TransportError):
                # A timed-out POST/PATCH may have succeeded remotely. Blindly
                # replaying it can duplicate candidates, notes or files; the
                # durable worker reconciles by GUID/marker/hash before retry.
                if not retry_safe or attempt >= self.config.max_retries:
                    raise
                wait = min(2**attempt, 30) + random.uniform(0, 0.25)
                await asyncio.sleep(wait)
                continue

            if response.status_code == 401 and attempt == 0:
                # Token may have been invalidated mid-flight — refresh once.
                self._token = None
                token = await self._ensure_token()
                headers["Authorization"] = f"Bearer {token}"
                continue

            retryable_status = response.status_code == 429 or (
                response.status_code >= 500 and retry_safe
            )
            if retryable_status:
                if attempt < self.config.max_retries:
                    retry_after = self._retry_after_seconds(response)
                    wait = (
                        retry_after
                        if retry_after is not None
                        else min(2**attempt, 30) + random.uniform(0, 0.25)
                    )
                    logger.warning(
                        "Traffit %s %s HTTP %d, backoff %.2fs (attempt %d/%d)",
                        method,
                        path,
                        response.status_code,
                        wait,
                        attempt + 1,
                        self.config.max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue
            return response

        assert response is not None  # loop always executes at least once
        return response

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json_body: Any = None,
        data: Any = None,
        files: Any = None,
        headers: Optional[Mapping[str, str]] = None,
        expected_statuses: Sequence[int] = (200,),
        retry_non_idempotent: bool = False,
    ) -> httpx.Response:
        """Public generic request which raises a structured API error."""
        response = await self._request_raw(
            method,
            path,
            params=params,
            json_body=json_body,
            data=data,
            files=files,
            extra_headers=headers,
            retry_non_idempotent=retry_non_idempotent,
        )
        if response.status_code not in expected_statuses:
            raise TraffitAPIError(
                method,
                path,
                response.status_code,
                response.text,
                retry_after_s=self._retry_after_seconds(response),
            )
        return response

    async def get_json(self, path: str) -> Any:
        response = await self.request("GET", path, expected_statuses=(200,))
        return response.json()

    async def post_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        expected_statuses: Sequence[int] = (200, 201, 204),
    ) -> Any:
        response = await self.request(
            "POST",
            path,
            json_body=dict(payload),
            expected_statuses=expected_statuses,
        )
        return response.json() if response.content else None

    async def patch_json(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        expected_statuses: Sequence[int] = (200, 204),
    ) -> Any:
        response = await self.request(
            "PATCH",
            path,
            json_body=dict(payload),
            expected_statuses=expected_statuses,
        )
        return response.json() if response.content else None

    async def post_multipart(
        self,
        path: str,
        *,
        filename: str,
        content: bytes,
        content_type: str = "application/octet-stream",
        field_name: str = "file",
        data: Optional[Mapping[str, Any]] = None,
        expected_statuses: Sequence[int] = (200, 201, 204),
    ) -> Any:
        response = await self.request(
            "POST",
            path,
            data=dict(data or {}),
            files={field_name: (filename, content, content_type)},
            expected_statuses=expected_statuses,
        )
        return response.json() if response.content else None

    async def fetch_metadata(self, method: str, path: str) -> Any:
        """Fetch tenant-specific request contract without performing a write."""
        method = method.upper()
        if method not in {"POST", "PATCH"}:
            raise ValueError("Traffit metadata is supported only for POST/PATCH")
        response = await self.request(
            method,
            path,
            headers={"X-Request-Metadata": "true"},
            expected_statuses=(200,),
        )
        return response.json()

    async def _get_raw(
        self,
        path: str,
        *,
        page: int = 1,
        page_size: int = 100,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> httpx.Response:
        return await self._request_raw(
            "GET",
            path,
            page=page,
            page_size=page_size,
            extra_headers=extra_headers,
        )

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
            if resp.status_code == 400 and active_filter is not None and page == 1:
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
            except json.JSONDecodeError as exc:
                raise TraffitIncompletePageError(
                    f"Bad JSON from {path} page={page}"
                ) from exc
            if not isinstance(items, list):
                raise TraffitIncompletePageError(
                    f"Expected list, got {type(items).__name__} from "
                    f"{path} page={page}"
                )
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
