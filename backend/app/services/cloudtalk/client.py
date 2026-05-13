"""CloudTalk REST API — async client with Basic Auth + retry/backoff.

Modeled on :mod:`app.services.autenti.client` (same retry/backoff shape) but
auth simplifies to HTTP Basic since CloudTalk uses a static API Key ID/Secret
pair instead of OAuth2.

Used by:
- ``/api/health`` — :meth:`CloudTalkClient.ping` reports CloudTalk reachability
- ``/api/cloudtalk/agents`` — :meth:`list_agents` for agent ↔ user mapping
- ``/api/cloudtalk/initiate-call`` — :meth:`initiate_call` for click-to-call
- ``app.tasks.cloudtalk_sync`` — :meth:`list_calls` for historical backfill

Reference: https://my.cloudtalk.io/api (auth + endpoint shapes per dashboard).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Exceptions ─────────────────────────────────────────────────────────────


class CloudTalkError(Exception):
    """Base for any CloudTalk integration failure."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"CloudTalk error {status}: {body[:200]}")
        self.status = status
        self.body = body


class CloudTalkAuthError(CloudTalkError):
    """401/403 — API Key pair invalid or revoked."""


class CloudTalkNotFoundError(CloudTalkError):
    """404 — agent/call/resource gone."""


class CloudTalkRateLimitError(CloudTalkError):
    """429 after retries exhausted."""


# ── Config ─────────────────────────────────────────────────────────────────


@dataclass
class CloudTalkConfig:
    base_url: str
    api_key_id: str
    api_key_secret: str
    timeout_s: float = 30.0
    max_retries: int = 3

    @classmethod
    def from_settings(cls) -> "CloudTalkConfig":
        """Read from app.core.config.settings. Raises if credentials missing.

        Caller is responsible for guarding with ``settings.CLOUDTALK_ENABLED``
        before constructing — the killswitch check belongs to the API/task
        layer, not the transport.
        """
        if not settings.CLOUDTALK_API_KEY_ID or not settings.CLOUDTALK_API_KEY_SECRET:
            raise RuntimeError(
                "CLOUDTALK_API_KEY_ID and CLOUDTALK_API_KEY_SECRET must be set "
                "in environment (generated in CloudTalk dashboard → Settings → "
                "API Keys; secret shown ONCE at creation)"
            )
        return cls(
            base_url=settings.CLOUDTALK_BASE_URL.rstrip("/"),
            api_key_id=settings.CLOUDTALK_API_KEY_ID,
            api_key_secret=settings.CLOUDTALK_API_KEY_SECRET,
        )


# ── Client ─────────────────────────────────────────────────────────────────


class CloudTalkClient:
    """Async client. Use as ``async with CloudTalkClient(config) as c:``.

    All public methods raise :class:`CloudTalkAuthError`,
    :class:`CloudTalkNotFoundError`, :class:`CloudTalkRateLimitError`, or
    generic :class:`CloudTalkError` on failure. Successful responses are
    decoded JSON.
    """

    def __init__(self, config: CloudTalkConfig) -> None:
        self.config = config
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "CloudTalkClient":
        self._http = httpx.AsyncClient(
            timeout=self.config.timeout_s,
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _auth_header(self) -> str:
        """Basic Auth — base64(KEY_ID:KEY_SECRET)."""
        token = base64.b64encode(
            f"{self.config.api_key_id}:{self.config.api_key_secret}".encode("utf-8")
        ).decode("ascii")
        return f"Basic {token}"

    # ── Low-level request with retry on 429/5xx ────────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> httpx.Response:
        """Generic CloudTalk request with retries.

        Raises typed CloudTalkError on terminal failure; returns the raw
        response on 2xx so callers can decide between ``.json()`` and
        ``.content``. Auth header is reconstructed every attempt — cheap
        and means a key rotation mid-flight on retry will pick up the new
        value (if settings reload — currently we don't, but the structure
        is ready).
        """
        assert self._http is not None
        url = path if path.startswith("http") else f"{self.config.base_url}{path}"

        last_resp: Optional[httpx.Response] = None
        for attempt in range(self.config.max_retries + 1):
            headers = {
                "Authorization": self._auth_header(),
                "Accept": "application/json",
            }
            if json_body is not None:
                headers["Content-Type"] = "application/json"

            resp = await self._http.request(
                method,
                url,
                headers=headers,
                json=json_body,
                params=params,
            )
            last_resp = resp

            if 200 <= resp.status_code < 300:
                return resp

            if resp.status_code in (401, 403):
                raise CloudTalkAuthError(resp.status_code, resp.text)

            if resp.status_code == 404:
                raise CloudTalkNotFoundError(404, resp.text)

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.config.max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "CloudTalk %s %s HTTP %d — backoff %ds (attempt %d/%d)",
                        method,
                        path,
                        resp.status_code,
                        wait,
                        attempt + 1,
                        self.config.max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code == 429:
                    raise CloudTalkRateLimitError(429, resp.text)

            raise CloudTalkError(resp.status_code, resp.text)

        assert last_resp is not None
        raise CloudTalkError(last_resp.status_code, last_resp.text)

    # ── High-level operations ──────────────────────────────────────────────

    async def ping(self) -> bool:
        """Liveness probe for /api/health. True iff credentials reach a 2xx.

        Hits the cheapest documented endpoint (``/agents/index.json?limit=1``).
        Auth failures bubble up as :class:`CloudTalkAuthError`; transport
        errors as :class:`CloudTalkError`. Healthcheck wraps in a 2s timeout
        and treats any exception as ``degraded``.
        """
        resp = await self._request("GET", "/agents/index.json", params={"limit": 1})
        return 200 <= resp.status_code < 300

    async def list_agents(
        self, *, limit: int = 100, page: int = 1
    ) -> list[dict[str, Any]]:
        """GET /agents/index.json — paginated list of CloudTalk agents.

        Returns the ``responseData.data`` array (each item: id, firstname,
        lastname, email, default_number, …). Falls back to the whole JSON
        if shape diverges (defensive — CloudTalk dashboard occasionally
        reshapes responses across plan tiers).
        """
        resp = await self._request(
            "GET",
            "/agents/index.json",
            params={"limit": limit, "page": page},
        )
        data = resp.json()
        if isinstance(data, dict):
            response_data = data.get("responseData")
            if isinstance(response_data, dict):
                agents = response_data.get("data")
                if isinstance(agents, list):
                    return [a.get("Agent", a) if isinstance(a, dict) else a for a in agents]
        if isinstance(data, list):
            return data
        return []

    async def list_calls(
        self,
        *,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        """GET /calls/index.json — paginated call history.

        ``date_from`` / ``date_to`` are ISO-8601 strings (YYYY-MM-DD or full
        timestamp). Returns the ``responseData.data`` array; defensive
        fallback as in :meth:`list_agents`.
        """
        params: dict[str, Any] = {"limit": limit, "page": page}
        if date_from:
            params["date_from"] = date_from
        if date_to:
            params["date_to"] = date_to
        resp = await self._request("GET", "/calls/index.json", params=params)
        data = resp.json()
        if isinstance(data, dict):
            response_data = data.get("responseData")
            if isinstance(response_data, dict):
                calls = response_data.get("data")
                if isinstance(calls, list):
                    return calls
        if isinstance(data, list):
            return data
        return []

    async def initiate_call(
        self, *, agent_id: int, phone_number: str
    ) -> dict[str, Any]:
        """POST /calls/create.json — click-to-call from agent to phone.

        CloudTalk rings the agent's softphone first; once answered it dials
        ``phone_number``. ``agent_id`` is the CloudTalk-side ID (mapped via
        ``users.cloudtalk_agent_id``). Phone should be E.164 with the
        leading ``+``; CloudTalk accepts other shapes but normalization is
        cheap insurance.
        """
        resp = await self._request(
            "POST",
            "/calls/create.json",
            json_body={"agent_id": agent_id, "callee_number": phone_number},
        )
        return resp.json() if resp.content else {}
