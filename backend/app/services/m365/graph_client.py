"""Thin async wrapper over Microsoft Graph.

Per-connection instance:
- Reads encrypted tokens from `M365Connection`, decrypts in memory.
- On 401 → refreshes, re-encrypts, persists row, retries once.
- On 429/503 → honors Retry-After (cap 60s), exponential backoff on repeat.
- On network errors → retries 2× with jitter.

A class-level semaphore throttles concurrent Graph calls across the whole
process (Graph allows 10,000 req / 10 min / app — with 4 concurrent and
paginated sync we stay well under).
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.encryption import get_token_cipher
from app.models.m365 import M365Connection, M365SyncStatus
from app.services.m365 import oauth as m365_oauth

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_CONCURRENCY = 4
_MAX_RETRIES_NETWORK = 2
_RETRY_AFTER_CAP_SECONDS = 60


class GraphRequestError(RuntimeError):
    """Non-retriable Graph response."""

    def __init__(self, status: int, body: Any) -> None:
        super().__init__(f"Graph {status}: {body!r}")
        self.status = status
        self.body = body


class GraphClient:
    """One instance per sync — holds a single user's token + session.

    Tokens are refreshed lazily when Graph returns 401. We re-encrypt and
    persist the new refresh_token (Graph rotates them), so the next sync picks
    up without user intervention.
    """

    _semaphore: asyncio.Semaphore = asyncio.Semaphore(_CONCURRENCY)

    def __init__(self, connection: M365Connection, db: AsyncSession) -> None:
        self._conn = connection
        self._db = db
        self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self._cipher = get_token_cipher()
        # Decrypt once per instance — tokens stay in memory, never logged.
        self._access_token: str = self._cipher.decrypt(connection.access_token_ct)
        self._refresh_token: str = self._cipher.decrypt(connection.refresh_token_ct)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "GraphClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.close()

    # ── Core request with retry/refresh ─────────────────────────────────────
    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[dict] = None,
        json: Optional[Any] = None,
        headers: Optional[dict] = None,
        expect_json: bool = True,
    ) -> Any:
        if not url.startswith("http"):
            url = f"{GRAPH_BASE}{url}"
        hdrs = {"Authorization": f"Bearer {self._access_token}"}
        if headers:
            hdrs.update(headers)

        async with GraphClient._semaphore:
            refreshed_once = False
            network_tries = 0
            while True:
                try:
                    resp = await self._client.request(
                        method, url, params=params, json=json, headers=hdrs
                    )
                except (httpx.ConnectError, httpx.ReadTimeout, httpx.ReadError) as exc:
                    network_tries += 1
                    if network_tries > _MAX_RETRIES_NETWORK:
                        raise
                    await asyncio.sleep(1.0 + random.random() * 1.5)
                    continue

                # 401 → refresh once and retry.
                if resp.status_code == 401 and not refreshed_once:
                    refreshed_once = True
                    await self._refresh_and_persist()
                    hdrs["Authorization"] = f"Bearer {self._access_token}"
                    continue

                # 429 / 503 → honor Retry-After (clamped), then retry.
                if resp.status_code in (429, 503):
                    retry_after = _parse_retry_after(
                        resp.headers.get("Retry-After")
                    )
                    sleep_s = min(retry_after, _RETRY_AFTER_CAP_SECONDS)
                    logger.warning(
                        "Graph throttled %s — sleeping %ds", resp.status_code, sleep_s
                    )
                    await asyncio.sleep(sleep_s)
                    continue

                if resp.status_code >= 400:
                    body: Any
                    try:
                        body = resp.json()
                    except Exception:  # noqa: BLE001
                        body = resp.text
                    raise GraphRequestError(resp.status_code, body)

                if not expect_json or resp.status_code == 204:
                    return resp.content
                if not resp.content:
                    return {}
                return resp.json()

    async def _refresh_and_persist(self) -> None:
        """Refresh access token and persist rotated refresh token to DB."""
        logger.info(
            "Graph 401 — refreshing tokens for connection %s", self._conn.id
        )
        try:
            bundle = await m365_oauth.refresh_tokens(self._refresh_token)
        except m365_oauth.M365ReauthRequired:
            # Mark connection inactive so the sync loop skips it until user reconnects.
            self._conn.is_active = False
            self._conn.last_sync_status = M365SyncStatus.error
            self._conn.last_error = "refresh token invalid — user must reconnect"
            await self._db.commit()
            raise

        self._access_token = bundle.access_token
        self._refresh_token = bundle.refresh_token
        self._conn.access_token_ct = self._cipher.encrypt(bundle.access_token)
        self._conn.refresh_token_ct = self._cipher.encrypt(bundle.refresh_token)
        self._conn.expires_at = bundle.expires_at
        if bundle.scopes:
            self._conn.scopes_granted = bundle.scopes
        await self._db.commit()

    # ── Public surface ─────────────────────────────────────────────────────
    async def get(
        self, url: str, params: Optional[dict] = None
    ) -> Any:
        return await self._request("GET", url, params=params)

    async def post(self, url: str, json: Optional[Any] = None) -> Any:
        return await self._request("POST", url, json=json)

    async def patch(self, url: str, json: Optional[Any] = None) -> Any:
        return await self._request("PATCH", url, json=json)

    async def delete(self, url: str) -> None:
        await self._request("DELETE", url, expect_json=False)

    async def download(self, url: str) -> bytes:
        """GET with binary response — e.g. attachment /$value endpoints."""
        return await self._request("GET", url, expect_json=False)

    async def paginate(
        self, url: str, params: Optional[dict] = None
    ) -> AsyncIterator[dict]:
        """Yield each JSON page from an @odata.nextLink-driven collection.

        Ends when the page contains `@odata.deltaLink` (terminal) or no
        `@odata.nextLink`. Callers that care about the final deltaLink should
        read it from the last yielded page.
        """
        next_url: Optional[str] = url
        next_params: Optional[dict] = params
        while next_url:
            page = await self.get(next_url, params=next_params)
            yield page
            # Once we start following nextLink, don't re-apply the original params.
            next_params = None
            next_url = page.get("@odata.nextLink")
            if not next_url and page.get("@odata.deltaLink"):
                # Terminal page with deltaLink — stop.
                break


def _parse_retry_after(header: Optional[str]) -> float:
    if not header:
        return 2.0
    try:
        return float(header)
    except (TypeError, ValueError):
        pass
    # HTTP-date form → parse to seconds from now.
    try:
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(header)
        if dt is None:
            return 2.0
        delta = (dt - datetime.now(timezone.utc)).total_seconds()
        return max(0.5, delta)
    except Exception:  # noqa: BLE001
        return 2.0
