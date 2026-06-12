"""jambonz REST API — async control client (Bearer auth + retry/backoff).

Modeled on :mod:`app.services.cloudtalk.client` (same retry/backoff + async
context-manager shape). jambonz runs the SIP/WebRTC media plane on a SEPARATE
host (it cannot sit behind Coolify's Traefik HTTP proxy); NEXUS uses this client
only for the control plane:

- ``/api/health`` — :meth:`ping` reports gateway reachability
- fraud kill path — :meth:`hangup_call` force-terminates a runaway call
- reconciliation task — :meth:`get_call` / :meth:`list_calls`

Reference: https://api.jambonz.org (v1 Accounts/Calls REST shapes).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class JambonzError(Exception):
    """Base for any jambonz integration failure."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"jambonz error {status}: {body[:200]}")
        self.status = status
        self.body = body


class JambonzAuthError(JambonzError):
    """401/403 — API token invalid or revoked."""


class JambonzNotFoundError(JambonzError):
    """404 — account/call resource gone."""


@dataclass
class JambonzConfig:
    base_url: str
    api_token: str
    account_sid: str
    timeout_s: float = 30.0
    max_retries: int = 3

    @classmethod
    def from_settings(cls) -> "JambonzConfig":
        """Read from app.core.config.settings. Raises if credentials missing.

        Caller guards with ``settings.OWN_DIALER_ENABLED`` before constructing.
        """
        if not settings.JAMBONZ_BASE_URL or not settings.JAMBONZ_API_TOKEN:
            raise RuntimeError(
                "JAMBONZ_BASE_URL and JAMBONZ_API_TOKEN must be set in "
                "environment (jambonz portal → Account → API key)."
            )
        if not settings.JAMBONZ_ACCOUNT_SID:
            raise RuntimeError("JAMBONZ_ACCOUNT_SID must be set in environment.")
        return cls(
            base_url=settings.JAMBONZ_BASE_URL.rstrip("/"),
            api_token=settings.JAMBONZ_API_TOKEN,
            account_sid=settings.JAMBONZ_ACCOUNT_SID,
        )


class JambonzClient:
    """Async client. Use as ``async with JambonzClient(config) as c:``."""

    def __init__(self, config: JambonzConfig) -> None:
        self.config = config
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "JambonzClient":
        self._http = httpx.AsyncClient(
            timeout=self.config.timeout_s, follow_redirects=True
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _account_path(self, suffix: str = "") -> str:
        return f"/v1/Accounts/{self.config.account_sid}{suffix}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
    ) -> httpx.Response:
        """Generic jambonz request with retry on 429/5xx. Returns the 2xx response."""
        assert self._http is not None
        url = path if path.startswith("http") else f"{self.config.base_url}{path}"

        last_resp: Optional[httpx.Response] = None
        for attempt in range(self.config.max_retries + 1):
            headers = {
                "Authorization": f"Bearer {self.config.api_token}",
                "Accept": "application/json",
            }
            if json_body is not None:
                headers["Content-Type"] = "application/json"

            resp = await self._http.request(
                method, url, headers=headers, json=json_body
            )
            last_resp = resp

            if 200 <= resp.status_code < 300:
                return resp
            if resp.status_code in (401, 403):
                raise JambonzAuthError(resp.status_code, resp.text)
            if resp.status_code == 404:
                raise JambonzNotFoundError(404, resp.text)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.config.max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "jambonz %s %s HTTP %d — backoff %ds (attempt %d/%d)",
                        method,
                        path,
                        resp.status_code,
                        wait,
                        attempt + 1,
                        self.config.max_retries,
                    )
                    await asyncio.sleep(wait)
                    continue
            raise JambonzError(resp.status_code, resp.text)

        assert last_resp is not None
        raise JambonzError(last_resp.status_code, last_resp.text)

    async def ping(self) -> bool:
        """Liveness probe for /api/health. True iff the account is reachable."""
        resp = await self._request("GET", self._account_path())
        return 200 <= resp.status_code < 300

    async def get_call(self, call_sid: str) -> dict[str, Any]:
        """GET /v1/Accounts/{sid}/Calls/{call_sid} — current call state."""
        resp = await self._request("GET", self._account_path(f"/Calls/{call_sid}"))
        return resp.json() if resp.content else {}

    async def list_calls(self) -> list[dict[str, Any]]:
        """GET /v1/Accounts/{sid}/Calls — in-progress calls (reconciliation)."""
        resp = await self._request("GET", self._account_path("/Calls"))
        data = resp.json()
        return data if isinstance(data, list) else data.get("data", [])

    async def hangup_call(self, call_sid: str) -> None:
        """DELETE /v1/Accounts/{sid}/Calls/{call_sid} — force-terminate a call.

        The fraud kill path: a runaway/over-cap call can be cut server-side.
        """
        await self._request("DELETE", self._account_path(f"/Calls/{call_sid}"))
