"""Microsoft 365 OAuth 2.0 authorization code flow (with PKCE).

Uses MSAL's `ConfidentialClientApplication` for the token dance. We wrap it
because:
- MSAL is sync — we offload to threads where needed.
- We need a richer `TokenBundle` shape than MSAL's raw dict.
- State is a signed JWT (10-min TTL) containing `user_id` + `pkce_verifier`,
  so the unauthenticated `/callback` can reconstruct session-less context.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from msal import ConfidentialClientApplication

from app.core.config import settings
from app.services.m365.provider import TokenBundle

logger = logging.getLogger(__name__)

# JWT algo matches the app's main SECRET_KEY flow so ops have one thing to know.
_STATE_ALGORITHM = "HS256"
_STATE_TTL_SECONDS = 600  # 10 minutes


class M365ReauthRequired(RuntimeError):
    """Refresh failed with invalid_grant — user must re-run OAuth flow."""


class M365NotConfigured(RuntimeError):
    """Client ID or secret missing — cannot do OAuth."""


# ── PKCE ─────────────────────────────────────────────────────────────────────


def generate_pkce_pair() -> tuple[str, str]:
    """Return (verifier, challenge). Verifier is 43-128 chars, URL-safe base64."""
    verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ── State JWT ────────────────────────────────────────────────────────────────


def _state_signing_key() -> str:
    """Use dedicated key if set, else fall back to main SECRET_KEY."""
    return settings.M365_STATE_SIGNING_KEY or settings.SECRET_KEY


def sign_state(user_id: int, pkce_verifier: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "pkce": pkce_verifier,
        "iat": now,
        "exp": now + timedelta(seconds=_STATE_TTL_SECONDS),
        "purpose": "m365_oauth_state",
    }
    return jwt.encode(payload, _state_signing_key(), algorithm=_STATE_ALGORITHM)


def verify_state(token: str) -> tuple[int, str]:
    """Return (user_id, pkce_verifier) or raise JWTError on invalid/expired."""
    try:
        payload = jwt.decode(token, _state_signing_key(), algorithms=[_STATE_ALGORITHM])
    except JWTError as exc:
        logger.info("m365 state verify failed: %s", exc)
        raise
    if payload.get("purpose") != "m365_oauth_state":
        raise JWTError("wrong purpose")
    user_id = int(payload["sub"])
    pkce = str(payload["pkce"])
    return user_id, pkce


# ── MSAL client + authorize URL ──────────────────────────────────────────────


def _require_client() -> ConfidentialClientApplication:
    if not settings.M365_CLIENT_ID or not settings.M365_CLIENT_SECRET:
        raise M365NotConfigured(
            "M365_CLIENT_ID / M365_CLIENT_SECRET are empty. IT Admin must register "
            "the Azure AD app and provide these (see plan §1)."
        )
    authority = f"https://login.microsoftonline.com/{settings.M365_TENANT_ID}"
    return ConfidentialClientApplication(
        client_id=settings.M365_CLIENT_ID,
        client_credential=settings.M365_CLIENT_SECRET,
        authority=authority,
    )


def build_authorize_url(state: str, pkce_verifier: str) -> str:
    """Return the Microsoft login URL the user is redirected to."""
    _, challenge = _derive_challenge(pkce_verifier)
    client = _require_client()
    # MSAL returns str; we trust the library to URL-encode correctly.
    return client.get_authorization_request_url(
        scopes=settings.M365_SCOPES,
        redirect_uri=settings.M365_REDIRECT_URI,
        state=state,
        code_challenge=challenge,
        code_challenge_method="S256",
        prompt="select_account",  # always show account picker — recruiters may have multiple
    )


def _derive_challenge(verifier: str) -> tuple[str, str]:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ── Token exchange + refresh ─────────────────────────────────────────────────


def _parse_token_response(raw: dict) -> TokenBundle:
    """MSAL's dict → TokenBundle. Raises KeyError on missing fields."""
    if "error" in raw:
        # Raise a generic exception; caller decides how to surface.
        desc = raw.get("error_description") or raw.get("error")
        raise RuntimeError(f"Microsoft OAuth error: {desc}")
    access_token = raw["access_token"]
    # MSAL exposes refresh tokens via a private claim; the library's own token
    # cache holds them, but we need the string for delayed refresh. The public
    # surface is `raw["refresh_token"]` for confidential clients.
    refresh_token = raw.get("refresh_token")
    if not refresh_token:
        # offline_access scope must be granted.
        raise RuntimeError(
            "No refresh_token in response. Did the user grant 'offline_access'?"
        )
    expires_in = int(raw.get("expires_in", 3600))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    scopes = raw.get("scope", "").split() if raw.get("scope") else []
    id_claims = raw.get("id_token_claims") or {}
    tenant_id = id_claims.get("tid") or settings.M365_TENANT_ID
    mailbox_upn = (
        id_claims.get("preferred_username")
        or id_claims.get("upn")
        or id_claims.get("email")
        or ""
    )
    return TokenBundle(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scopes=scopes,
        tenant_id=tenant_id,
        mailbox_upn=mailbox_upn,
    )


async def exchange_code(code: str, pkce_verifier: str) -> TokenBundle:
    client = _require_client()

    def _call() -> dict:
        return client.acquire_token_by_authorization_code(
            code=code,
            scopes=settings.M365_SCOPES,
            redirect_uri=settings.M365_REDIRECT_URI,
            code_verifier=pkce_verifier,
        )

    raw = await asyncio.to_thread(_call)
    return _parse_token_response(raw)


async def refresh_tokens(refresh_token: str) -> TokenBundle:
    client = _require_client()

    def _call() -> dict:
        return client.acquire_token_by_refresh_token(
            refresh_token=refresh_token,
            scopes=settings.M365_SCOPES,
        )

    raw = await asyncio.to_thread(_call)
    if raw.get("error") == "invalid_grant":
        raise M365ReauthRequired(raw.get("error_description", "invalid_grant"))
    return _parse_token_response(raw)


async def revoke(refresh_token: Optional[str]) -> None:
    """Best-effort revoke. Graph's /me/revokeSignInSessions needs admin scope,
    so for Phase 1 we simply drop the DB row and let the refresh_token rot.
    Future: call Graph revoke endpoint when we add admin-consent scopes."""
    if not refresh_token:
        return
    logger.info("m365 revoke: soft-revoke (DB row delete) — Graph call TBD")
