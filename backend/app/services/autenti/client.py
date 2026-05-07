"""Autenti Public API v2 (Bespin) — async REST client with OAuth2.

Modeled on :mod:`app.services.traffit.client`:
- OAuth2 client_credentials with cached access token + 5-min pre-refresh.
- Manual exponential backoff (`2**attempt`, max 3 retries) on 429/5xx.
- One automatic re-token attempt on 401 (token may be invalidated mid-flight).
- ``Idempotency-Key`` header on POSTs that create resources.

Auth fallback strategy (per plan §2): :meth:`_ensure_token` is the only place
that needs editing if Autenti sales does not grant ``bpa`` scope. Switching to
``authorization_code`` per-user only changes the token-acquisition method —
the rest of the methods remain agnostic.

Reference: https://developers.autenti.com/docs/autenti-public-api-v2
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


# ── Exceptions ─────────────────────────────────────────────────────────────


class AutentiError(Exception):
    """Base for any Autenti integration failure."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"Autenti error {status}: {body[:200]}")
        self.status = status
        self.body = body


class AutentiAuthError(AutentiError):
    """OAuth2 token request failed or 401 persisted after one re-token retry."""


class AutentiNotFoundError(AutentiError):
    """404 from Autenti — process / file / participant gone."""


class AutentiRateLimitError(AutentiError):
    """429 after retries exhausted."""


class AutentiWebhookError(Exception):
    """Webhook JWT verification or payload validation failed."""


# ── Config ─────────────────────────────────────────────────────────────────


@dataclass
class AutentiConfig:
    base_url: str
    oauth_url: str
    client_id: str
    client_secret: str
    scope: str
    timeout_s: float = 30.0
    max_retries: int = 3

    @classmethod
    def from_settings(cls) -> "AutentiConfig":
        """Read from app.core.config.settings. Raises if creds missing."""
        if not settings.AUTENTI_CLIENT_ID or not settings.AUTENTI_CLIENT_SECRET:
            raise RuntimeError(
                "AUTENTI_CLIENT_ID and AUTENTI_CLIENT_SECRET must be set "
                "in environment (provisioned by Autenti sales — see plan Phase 0)"
            )
        return cls(
            base_url=settings.AUTENTI_BASE_URL.rstrip("/"),
            oauth_url=settings.AUTENTI_OAUTH_URL,
            client_id=settings.AUTENTI_CLIENT_ID,
            client_secret=settings.AUTENTI_CLIENT_SECRET,
            scope=settings.AUTENTI_OAUTH_SCOPE,
        )


# ── Client ─────────────────────────────────────────────────────────────────


class AutentiClient:
    """Async client. Use as ``async with AutentiClient(config) as c:``.

    All public methods raise :class:`AutentiAuthError`,
    :class:`AutentiNotFoundError`, :class:`AutentiRateLimitError`, or generic
    :class:`AutentiError` on failure. Successful responses are decoded JSON
    (or bytes for binary downloads).
    """

    def __init__(self, config: AutentiConfig) -> None:
        self.config = config
        self._token: Optional[str] = None
        self._token_expires_at: Optional[datetime] = None
        self._http: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "AutentiClient":
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
        """Return a non-expired bearer token, refreshing if needed.

        Single point of change for grant-type fallback (plan §2).
        """
        now = datetime.now(timezone.utc)
        if (
            self._token is not None
            and self._token_expires_at is not None
            and now < self._token_expires_at - timedelta(minutes=5)
        ):
            return self._token

        assert self._http is not None
        body = {
            "grant_type": "client_credentials",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "scope": self.config.scope,
        }
        resp = await self._http.post(
            self.config.oauth_url,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise AutentiAuthError(resp.status_code, resp.text)
        data = resp.json()
        self._token = data["access_token"]
        expires_in = int(data.get("expires_in", 3600))
        self._token_expires_at = now + timedelta(seconds=expires_in)
        logger.info(
            "Autenti token refreshed (expires_in=%ds, scope=%s)",
            expires_in,
            data.get("scope"),
        )
        assert self._token is not None
        return self._token

    # ── Low-level request with retry + auto-reauth ─────────────────────────

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict] = None,
        files: Optional[dict] = None,
        idempotency_key: Optional[str] = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        """Generic Autenti request with retries.

        Raises typed AutentiError on terminal failure; returns the raw response
        on 2xx so callers can decide between ``.json()`` / ``.content``.
        """
        assert self._http is not None
        token = await self._ensure_token()

        url = path if path.startswith("http") else f"{self.config.base_url}{path}"

        last_resp: Optional[httpx.Response] = None
        for attempt in range(self.config.max_retries + 1):
            headers: dict[str, str] = {
                "Authorization": f"Bearer {token}",
                "Accept": accept,
            }
            if idempotency_key:
                headers["Idempotency-Key"] = idempotency_key
            if json_body is not None:
                headers["Content-Type"] = "application/json"

            resp = await self._http.request(
                method,
                url,
                headers=headers,
                json=json_body if files is None else None,
                files=files,
            )
            last_resp = resp

            if 200 <= resp.status_code < 300:
                return resp

            if resp.status_code == 401 and attempt == 0:
                # Token may have been invalidated mid-flight — force refresh.
                logger.warning("Autenti %s %s 401 — re-acquiring token", method, path)
                self._token = None
                token = await self._ensure_token()
                continue

            if resp.status_code == 401:
                raise AutentiAuthError(401, resp.text)

            if resp.status_code == 404:
                raise AutentiNotFoundError(404, resp.text)

            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.config.max_retries:
                    wait = 2**attempt
                    logger.warning(
                        "Autenti %s %s HTTP %d — backoff %ds (attempt %d/%d)",
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
                    raise AutentiRateLimitError(429, resp.text)

            # 4xx other than 401/404/429 — terminal client error.
            raise AutentiError(resp.status_code, resp.text)

        # Loop exhausted (should be unreachable — retries above either return
        # or raise). Defensive fallback.
        assert last_resp is not None
        raise AutentiError(last_resp.status_code, last_resp.text)

    # ── High-level operations ──────────────────────────────────────────────

    async def create_document_process(
        self,
        payload: dict,
        *,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """POST /document-processes — create a draft process.

        ``payload`` is the Autenti-shaped JSON (parties, files placeholders,
        constraints) — see :func:`app.services.autenti.sender._build_create_payload`
        in Phase 2. Returns the decoded response with ``id`` (process_id).
        """
        resp = await self._request(
            "POST",
            "/document-processes",
            json_body=payload,
            idempotency_key=idempotency_key,
        )
        return resp.json()

    async def upload_file(
        self,
        process_id: str,
        *,
        pdf_bytes: bytes,
        filename: str,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """POST /document-processes/{id}/files — attach the PDF to draft."""
        files = {"file": (filename, pdf_bytes, "application/pdf")}
        resp = await self._request(
            "POST",
            f"/document-processes/{process_id}/files",
            files=files,
            idempotency_key=idempotency_key,
        )
        return resp.json()

    async def send(
        self, process_id: str, *, idempotency_key: Optional[str] = None
    ) -> dict:
        """POST /document-processes/{id}/actions/send — finalize draft → notify signers."""
        resp = await self._request(
            "POST",
            f"/document-processes/{process_id}/actions/send",
            json_body={},
            idempotency_key=idempotency_key,
        )
        return resp.json()

    async def withdraw(self, process_id: str) -> dict:
        """POST /document-processes/{id}/actions/withdraw — cancel a sent process."""
        resp = await self._request(
            "POST",
            f"/document-processes/{process_id}/actions/withdraw",
            json_body={},
        )
        return resp.json()

    async def remind(self, process_id: str) -> dict:
        """POST /document-processes/{id}/actions/remind — nudge pending signers."""
        resp = await self._request(
            "POST",
            f"/document-processes/{process_id}/actions/remind",
            json_body={},
        )
        return resp.json()

    async def get_process(self, process_id: str) -> dict:
        """GET /document-processes/{id} — current status + participant events."""
        resp = await self._request("GET", f"/document-processes/{process_id}")
        return resp.json()

    async def download_signed_file(self, process_id: str) -> bytes:
        """GET signed file — returns raw PDF bytes.

        Autenti exposes the post-signature PDF under
        ``/document-processes/{id}/files/signed``. Raw octet stream.
        """
        resp = await self._request(
            "GET",
            f"/document-processes/{process_id}/files/signed",
            accept="application/pdf",
        )
        return resp.content
