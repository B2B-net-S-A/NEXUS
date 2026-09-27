"""Microsoft 365 OAuth 2.0 authorization code flow (with PKCE).

We talk to the Azure AD v2.0 endpoints directly (via httpx) instead of using
MSAL's ConfidentialClientApplication — MSAL 1.31's
`get_authorization_request_url` silently dropped our `code_challenge` kwarg,
so Azure generated its own PKCE challenge under the hood and then rejected
our verifier at the token exchange with AADSTS501481.

Flow:
- /authorize signs a state JWT with user_id + a random nonce ``n``; the PKCE
  verifier is DERIVED server-side (HMAC of the signing key and ``n``), so it
  never appears in the authorize URL, and builds the authorize URL by hand.
- /callback decodes state → nonce → verifier, consumes the nonce once
  (``consume_state``), posts the authorization_code grant to /token with
  code + code_verifier in the form body.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.app_setting import AppSetting
from app.services.m365.provider import TokenBundle

logger = logging.getLogger(__name__)

_STATE_ALGORITHM = "HS256"
_STATE_TTL_SECONDS = 600  # 10 minutes
# Scopes we always request on top of the configured M365_SCOPES.
# offline_access → refresh token; openid/profile → id_token with upn claim.
# Phase 7.2 footnote: ``GroupMember.Read.All`` (delegated + admin-consent-
# required) is appended dynamically by :func:`_extra_scopes` when
# ``AAD_GROUP_RBAC_ENABLED=true`` so the mailbox reconnect path can refresh
# group memberships. Including it unconditionally would 65001/65004 every
# mailbox connection until admin consent is granted in Azure.
_EXTRA_SCOPES_BASE = (
    "offline_access",
    "openid",
    "profile",
)
_RBAC_SCOPE = "GroupMember.Read.All"


def _extra_scopes() -> tuple[str, ...]:
    if settings.AAD_GROUP_RBAC_ENABLED:
        return _EXTRA_SCOPES_BASE + (_RBAC_SCOPE,)
    return _EXTRA_SCOPES_BASE


class M365ReauthRequired(RuntimeError):
    """Refresh failed with invalid_grant — user must re-run OAuth flow."""


class M365NotConfigured(RuntimeError):
    """Client ID or secret missing — cannot do OAuth."""


# ── PKCE ─────────────────────────────────────────────────────────────────────


def _derive_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# ── State JWT ────────────────────────────────────────────────────────────────


def _state_signing_key() -> str:
    return settings.M365_STATE_SIGNING_KEY or settings.SECRET_KEY


_STATE_PURPOSE = "m365_oauth_state"


# Runda 11 (SEC, bliźniak R9-N1-4 i R10-N10-8): weryfikator PKCE jechał JAWNIE
# w ``state``, a ``state`` wraca w adresie callbacku razem z kodem autoryzacji
# (historia przeglądarki, logi proxy, Referer) i był wielokrotnego użytku przez
# 10 min. Teraz ``state`` niesie tylko losowy ``n``, weryfikator wylicza serwer
# (HMAC klucza podpisu), a callback zużywa ``n`` jednorazowo (``consume_state``).
def pkce_verifier_for(nonce: str) -> str:
    digest = hmac.new(
        _state_signing_key().encode("utf-8"),
        f"m365-pkce:{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    # 43 znaki alfabetu base64url — mieści się w RFC 7636 (43–128).
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class M365OAuthState:
    user_id: int
    verifier: str
    nonce_digest: str
    expires_at: datetime


def sign_state(user_id: int, nonce: Optional[str] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "n": nonce or secrets.token_urlsafe(24),
        "iat": now,
        "exp": now + timedelta(seconds=_STATE_TTL_SECONDS),
        "purpose": _STATE_PURPOSE,
    }
    return jwt.encode(payload, _state_signing_key(), algorithm=_STATE_ALGORITHM)


def verify_state(token: str) -> M365OAuthState:
    """Stan łączenia skrzynki albo ``JWTError`` — także przy obcym ``purpose``
    i przy ``state`` sprzed rundy 11 (bez ``n``)."""
    try:
        payload = jwt.decode(token, _state_signing_key(), algorithms=[_STATE_ALGORITHM])
    except JWTError as exc:
        logger.info("m365 state verify failed: %s", type(exc).__name__)
        raise
    if payload.get("purpose") != _STATE_PURPOSE:
        raise JWTError("wrong purpose")
    nonce = payload.get("n")
    if not isinstance(nonce, str) or not nonce:
        raise JWTError("state without nonce")
    return M365OAuthState(
        user_id=int(payload["sub"]),
        verifier=pkce_verifier_for(nonce),
        nonce_digest=hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc),
    )


_CONSUMED_STATES_KEY = "m365_oauth_consumed_states"


async def consume_state(db: AsyncSession, state: M365OAuthState) -> bool:
    """Zużywa ``state`` (bez commitu). ``False`` = ten ``state`` już wrócił.

    Ten sam wzór co ``jjit_connection.consume_state``: wiersz ``app_settings``
    pod blokadą serializuje równoległe callbacki; w wartości leżą skróty ``n``
    (nie same ``n``) do upływu ich ważności.
    """
    await db.execute(
        pg_insert(AppSetting)
        .values(key=_CONSUMED_STATES_KEY, value={})
        .on_conflict_do_nothing(index_elements=["key"])
    )
    row = await db.scalar(
        select(AppSetting)
        .where(AppSetting.key == _CONSUMED_STATES_KEY)
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    seen: dict[str, str] = {}
    for digest, expires in (row.value or {}).items():
        try:
            if datetime.fromisoformat(expires) > now:
                seen[digest] = expires
        except (TypeError, ValueError):
            continue
    if state.nonce_digest in seen:
        return False
    seen[state.nonce_digest] = state.expires_at.isoformat()
    row.value = seen
    await db.flush()
    return True


def new_authorize_url(user_id: int) -> str:
    """Adres logowania Microsoft dla łączenia skrzynki (weryfikator poza URL-em)."""
    nonce = secrets.token_urlsafe(24)
    return build_authorize_url(sign_state(user_id, nonce), pkce_verifier_for(nonce))


# ── Endpoint builders ────────────────────────────────────────────────────────


def _require_config() -> None:
    if not settings.M365_CLIENT_ID or not settings.M365_CLIENT_SECRET:
        raise M365NotConfigured(
            "M365_CLIENT_ID / M365_CLIENT_SECRET are empty. IT Admin must register "
            "the Azure AD app and provide these."
        )


def _tenant_url_fragment() -> str:
    # For authorize/token endpoints we always hit the tenant-specific URL
    # because we know it from admin creds. "common" works too but tenant-
    # specific gives better error messages.
    return settings.M365_TENANT_ID or "common"


def _scope_string() -> str:
    return " ".join([*settings.M365_SCOPES, *_extra_scopes()])


def _authorize_endpoint() -> str:
    return f"https://login.microsoftonline.com/{_tenant_url_fragment()}/oauth2/v2.0/authorize"


def _token_endpoint() -> str:
    return (
        f"https://login.microsoftonline.com/{_tenant_url_fragment()}/oauth2/v2.0/token"
    )


# ── Authorize URL ────────────────────────────────────────────────────────────


def build_authorize_url(state: str, pkce_verifier: str) -> str:
    """Return the Microsoft login URL the user is redirected to."""
    _require_config()
    challenge = _derive_challenge(pkce_verifier)
    params = {
        "client_id": settings.M365_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.M365_REDIRECT_URI,
        "response_mode": "query",
        "scope": _scope_string(),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return f"{_authorize_endpoint()}?{urlencode(params)}"


# ── Token exchange + refresh ─────────────────────────────────────────────────


async def _post_token(data: dict) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _token_endpoint(),
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    try:
        body = resp.json()
    except ValueError:
        body = {"error": "invalid_response", "raw": resp.text}
    if resp.status_code >= 400 or "error" in body:
        err = body.get("error") or f"http_{resp.status_code}"
        desc = body.get("error_description") or body.get("raw") or "no details"
        # Re-raise with the raw payload so caller can branch on invalid_grant.
        raise RuntimeError(f"Microsoft OAuth error: {err}: {desc}")
    return body


def _decode_id_token(id_token: Optional[str]) -> dict:
    """Base64-decode the claims section without signature verification.

    Safe because we received the token over HTTPS from the Microsoft token
    endpoint; we only use its claims for display (mailbox UPN, tenant id).
    """
    if not id_token:
        return {}
    parts = id_token.split(".")
    if len(parts) < 2:
        return {}
    body = parts[1]
    # pad to multiple of 4
    body += "=" * (-len(body) % 4)
    try:
        return json.loads(base64.urlsafe_b64decode(body).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _parse_token_response(raw: dict) -> TokenBundle:
    access_token = raw.get("access_token")
    if not access_token:
        raise RuntimeError(f"Token response missing access_token: {raw}")
    refresh_token = raw.get("refresh_token")
    if not refresh_token:
        raise RuntimeError(
            "No refresh_token in response. Did the user grant 'offline_access'?"
        )
    expires_in = int(raw.get("expires_in", 3600))
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    scope_raw = raw.get("scope", "")
    scopes = scope_raw.split() if scope_raw else []
    id_claims = _decode_id_token(raw.get("id_token"))
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
        oid=(str(id_claims.get("oid") or "").strip() or None),
    )


async def exchange_code(code: str, pkce_verifier: str) -> TokenBundle:
    _require_config()
    data = {
        "client_id": settings.M365_CLIENT_ID,
        "client_secret": settings.M365_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.M365_REDIRECT_URI,
        "code_verifier": pkce_verifier,
        "scope": _scope_string(),
    }
    raw = await _post_token(data)
    return _parse_token_response(raw)


async def refresh_tokens(refresh_token: str) -> TokenBundle:
    _require_config()
    data = {
        "client_id": settings.M365_CLIENT_ID,
        "client_secret": settings.M365_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "scope": _scope_string(),
    }
    try:
        raw = await _post_token(data)
    except RuntimeError as exc:
        msg = str(exc)
        if "invalid_grant" in msg:
            raise M365ReauthRequired(msg) from exc
        raise
    return _parse_token_response(raw)


async def revoke(refresh_token: Optional[str]) -> None:
    """Best-effort revoke — Graph's /me/revokeSignInSessions needs admin scope,
    so Phase 1 just drops the DB row and lets the refresh_token rot."""
    if not refresh_token:
        return
    logger.info("m365 revoke: soft-revoke (DB row delete) — Graph call TBD")
