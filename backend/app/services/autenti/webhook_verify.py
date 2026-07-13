"""Verify Autenti webhook JWT signatures against the public JWKS endpoint.

Autenti signs every webhook body as a JWT (RS256). We refuse to act on a
payload that doesn't verify against the keys at
``settings.AUTENTI_WEBHOOK_JWKS_URL``. Plan §4 → "Inbound webhook flow".

Cache strategy (plan §1):
- Module-level dict keyed by JWK ``kid``.
- Refreshed when an unknown ``kid`` appears OR after 24h whichever is sooner.
- On fetch failure we keep the previous cache (Sentry alert) and refuse the
  webhook — never "trust unsigned".

Replay protection lives one layer up: :mod:`webhook_handler` inserts every
event_id into ``document_signature_events`` with a unique constraint. This
module only validates cryptographic authenticity + clock-skew window.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.jwt import JWTError, jwt, key_from_jwk

logger = logging.getLogger(__name__)


class AutentiWebhookError(Exception):
    """Webhook verification or payload validation failed."""


# Module-level mutable cache. Acceptable here because there's at most ONE
# JWKS endpoint per process and we never mutate the dict from inside the
# request path without the lock.
_jwks_cache: dict[str, dict[str, Any]] = {}
_jwks_fetched_at: float = 0.0
_jwks_lock = asyncio.Lock()
_CACHE_TTL_SECONDS = 24 * 60 * 60


async def _fetch_jwks(force: bool = False) -> dict[str, dict[str, Any]]:
    """Refresh the JWK cache from Autenti's well-known endpoint.

    Returns the new keyed-by-kid dict. Never replaces the cache with an
    empty/error response — the cache is replaced atomically only on a
    successful fetch with at least one key.

    ``force=True`` skips the TTL gate (used when a webhook arrives with an
    unknown ``kid``).
    """
    global _jwks_cache, _jwks_fetched_at

    async with _jwks_lock:
        now = time.time()
        if not force and _jwks_cache and (now - _jwks_fetched_at) < _CACHE_TTL_SECONDS:
            return _jwks_cache

        url = settings.AUTENTI_WEBHOOK_JWKS_URL
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
        except httpx.HTTPError as exc:
            if _jwks_cache:
                logger.warning(
                    "JWKS fetch failed (%s); keeping prior cache (%d keys)",
                    exc,
                    len(_jwks_cache),
                )
                return _jwks_cache
            raise AutentiWebhookError(
                f"JWKS fetch failed and no cached keys: {exc}"
            ) from exc

        if resp.status_code != 200:
            if _jwks_cache:
                logger.warning(
                    "JWKS HTTP %d at %s; keeping prior cache",
                    resp.status_code,
                    url,
                )
                return _jwks_cache
            raise AutentiWebhookError(
                f"JWKS HTTP {resp.status_code}: {resp.text[:200]}"
            )

        keys = resp.json().get("keys", [])
        if not keys:
            if _jwks_cache:
                logger.warning("JWKS response empty; keeping prior cache")
                return _jwks_cache
            raise AutentiWebhookError("JWKS response had no keys")

        new_cache: dict[str, dict[str, Any]] = {}
        for key in keys:
            kid = key.get("kid")
            if kid:
                new_cache[kid] = key

        _jwks_cache = new_cache
        _jwks_fetched_at = now
        logger.info("JWKS refreshed: %d keys", len(new_cache))
        return _jwks_cache


def _reset_cache_for_tests() -> None:
    """Test helper — clear module state between tests."""
    global _jwks_cache, _jwks_fetched_at
    _jwks_cache = {}
    _jwks_fetched_at = 0.0


async def verify_jwt(token: str) -> dict[str, Any]:
    """Verify a webhook JWT and return its decoded claims.

    Validates:
    - RS256 signature against a key in the JWKS cache (refreshed on unknown kid).
    - ``iat`` within the configured clock-skew window (default 24h).

    Raises :class:`AutentiWebhookError` on any failure — the caller should
    return HTTP 401 to refuse the webhook.
    """
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise AutentiWebhookError(f"Cannot decode JWT header: {exc}") from exc

    kid = unverified_header.get("kid")
    if not kid:
        raise AutentiWebhookError("JWT header has no `kid`")

    cache = await _fetch_jwks(force=False)
    if kid not in cache:
        # Possible key rotation — try a forced refresh.
        cache = await _fetch_jwks(force=True)
        if kid not in cache:
            raise AutentiWebhookError(f"Unknown JWT kid={kid!r}")

    try:
        claims = jwt.decode(
            token,
            key_from_jwk(cache[kid]),
            algorithms=["RS256"],
            options={"verify_aud": False},
        )
    except JWTError as exc:
        raise AutentiWebhookError(f"JWT signature/claims invalid: {exc}") from exc

    iat = claims.get("iat")
    if iat is not None:
        max_age = settings.AUTENTI_WEBHOOK_IAT_MAX_AGE_HOURS * 3600
        age = int(time.time()) - int(iat)
        if age > max_age:
            raise AutentiWebhookError(
                f"JWT iat is {age}s old (max {max_age}s) — replay protection"
            )

    return claims


def parse_iat(claims: dict[str, Any]) -> Optional[datetime]:
    """Convert ``iat`` Unix epoch (seconds) to a tz-aware datetime."""
    iat = claims.get("iat")
    if iat is None:
        return None
    try:
        return datetime.fromtimestamp(int(iat), tz=timezone.utc)
    except (TypeError, ValueError):
        return None
