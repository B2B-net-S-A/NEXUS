"""Microsoft SSO login — Faza B.

Three endpoints under ``/api/auth/microsoft``:

- ``GET /authorize``        → returns ``{authorize_url}`` for the frontend
- ``GET /callback``         → OAuth redirect target (unauth); upserts user,
                              persists tokens behind a short-lived UUID,
                              redirects to ``/login/microsoft/callback?code=...``
- ``POST /exchange``        → consumes UUID, returns Nexus JWTs

Reuses helpers from :mod:`app.services.m365.oauth` (PKCE, signed state, token
endpoint POST, id_token decoding) — Azure AD app is shared with mailbox sync
(one client_id, two redirect URIs).

Rationale for the exchange-code dance: redirecting the frontend with tokens
in the query string would leak them into proxy logs / browser history /
Sentry breadcrumbs. The UUID is jednorazowy (60s TTL, ``consumed_at`` flag).
"""

# NB: nie używamy ``from __future__ import annotations`` — FastAPI body
# inference + Pydantic nie potrafi rozwiązać ForwardRef przy lazy
# annotacjach (PydanticUserError "TypeAdapter[Annotated[ForwardRef(...)]]
# is not fully defined"). Eager annotacje są tu OK — plik jest mały.

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import create_access_token, create_refresh_token
from app.models.auth_exchange_code import AuthExchangeCode
from app.models.user import User, UserRole
from app.services.m365 import oauth as m365_oauth

logger = logging.getLogger(__name__)

router = APIRouter()

# Login flow uses identity scopes only — separate from mailbox sync's
# Mail.* / Calendars.* scopes. ``offline_access`` keeps the refresh token in
# case we want to silently re-issue Nexus tokens later.
_LOGIN_SCOPES = ("openid", "profile", "email", "User.Read", "offline_access")

# Discriminator embedded in the state JWT — prevents a mailbox-state code
# from being replayed on the login callback (and vice versa).
_STATE_PURPOSE = "sso_login"
_STATE_TTL_SECONDS = 600  # 10 minutes — same as mailbox flow.

_EXCHANGE_TTL_SECONDS = 60


# ── Schemas ─────────────────────────────────────────────────────────────────


class AuthorizeResponse(BaseModel):
    authorize_url: str


class ExchangeRequest(BaseModel):
    code: str = Field(..., min_length=32, max_length=64)


class SsoUserSummary(BaseModel):
    id: int
    email: str
    name: str
    role: str
    profile_completed: bool


class ExchangeResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: SsoUserSummary


# ── Helpers ─────────────────────────────────────────────────────────────────


def _state_signing_key() -> str:
    return settings.M365_STATE_SIGNING_KEY or settings.SECRET_KEY


def _sign_login_state(pkce_verifier: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "pkce": pkce_verifier,
        "iat": now,
        "exp": now + timedelta(seconds=_STATE_TTL_SECONDS),
        "purpose": _STATE_PURPOSE,
    }
    return jwt.encode(payload, _state_signing_key(), algorithm="HS256")


def _verify_login_state(token: str) -> str:
    """Return PKCE verifier; raise JWTError on invalid/expired/wrong purpose."""
    payload = jwt.decode(token, _state_signing_key(), algorithms=["HS256"])
    if payload.get("purpose") != _STATE_PURPOSE:
        raise JWTError("wrong purpose for SSO login state")
    return str(payload["pkce"])


def _require_sso_configured() -> None:
    if not settings.M365_INTEGRATION_ENABLED:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft 365 integration is currently disabled.",
        )
    if not settings.M365_CLIENT_ID or not settings.M365_CLIENT_SECRET:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft SSO not configured (M365_CLIENT_ID / M365_CLIENT_SECRET empty).",
        )
    if not settings.MICROSOFT_LOGIN_REDIRECT_URI:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft SSO redirect URI not configured.",
        )


def _build_authorize_url(state: str, pkce_verifier: str) -> str:
    challenge = m365_oauth._derive_challenge(pkce_verifier)
    tenant = settings.M365_TENANT_ID or "common"
    params = {
        "client_id": settings.M365_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": settings.MICROSOFT_LOGIN_REDIRECT_URI,
        "response_mode": "query",
        "scope": " ".join(_LOGIN_SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    return (
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
        f"?{urlencode(params)}"
    )


async def _exchange_code_for_id_token(code: str, pkce_verifier: str) -> dict:
    """Trade authorization_code for id_token. Returns decoded id_token claims."""
    tenant = settings.M365_TENANT_ID or "common"
    data = {
        "client_id": settings.M365_CLIENT_ID,
        "client_secret": settings.M365_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings.MICROSOFT_LOGIN_REDIRECT_URI,
        "code_verifier": pkce_verifier,
        "scope": " ".join(_LOGIN_SCOPES),
    }
    # _post_token in m365.oauth uses tenant from settings; we cannot override
    # cleanly without duplicating it here, so re-implement with httpx directly.
    import httpx

    token_url = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    body = resp.json() if resp.content else {}
    if resp.status_code >= 400 or "error" in body:
        err = body.get("error", f"http_{resp.status_code}")
        desc = body.get("error_description") or "no details"
        raise RuntimeError(f"Microsoft OAuth error: {err}: {desc}")
    id_token = body.get("id_token")
    if not id_token:
        raise RuntimeError(f"Token response missing id_token: keys={list(body.keys())}")
    return m365_oauth._decode_id_token(id_token)


def _frontend_callback_url(**params: str) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/login/microsoft/callback?{urlencode(params)}"


def _frontend_login_error_url(reason: str) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/login?{urlencode({'error': reason[:120]})}"


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/authorize", response_model=AuthorizeResponse)
@limiter.limit("10/minute")
async def authorize(request: Request) -> AuthorizeResponse:
    """Build the Microsoft login URL. Frontend does ``window.location = url``."""
    _require_sso_configured()
    verifier, _ = m365_oauth.generate_pkce_pair()
    state = _sign_login_state(verifier)
    return AuthorizeResponse(authorize_url=_build_authorize_url(state, verifier))


@router.get("/callback", response_class=RedirectResponse)
@limiter.limit("20/minute")
async def callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """OAuth redirect target. Unauthenticated — identity comes from id_token.

    On success: redirect to ``/login/microsoft/callback?code=<uuid>`` (frontend
    POSTs that uuid to ``/exchange``). On error: redirect to ``/login?error=...``.
    """
    if error:
        logger.info("sso callback error: %s — %s", error, error_description)
        return RedirectResponse(
            _frontend_login_error_url(error_description or error), status_code=302
        )
    if not code or not state:
        return RedirectResponse(
            _frontend_login_error_url("Missing code/state"), status_code=302
        )

    try:
        pkce_verifier = _verify_login_state(state)
    except JWTError:
        return RedirectResponse(
            _frontend_login_error_url("State expired or invalid - try again"),
            status_code=302,
        )

    try:
        claims = await _exchange_code_for_id_token(code, pkce_verifier)
    except Exception as exc:  # noqa: BLE001
        logger.exception("sso code exchange failed")
        return RedirectResponse(
            _frontend_login_error_url(f"Token exchange failed: {exc!r}"),
            status_code=302,
        )

    email = (
        claims.get("preferred_username")
        or claims.get("upn")
        or claims.get("email")
        or ""
    )
    azure_oid = claims.get("oid") or ""
    name = claims.get("name") or email.split("@")[0]

    if not email or not azure_oid:
        logger.warning("sso callback missing email/oid in claims keys=%s", list(claims))
        return RedirectResponse(
            _frontend_login_error_url("Missing identity claims"), status_code=302
        )

    # Domain whitelist — empty list rejects every domain (fail-closed).
    domain = email.split("@")[-1].lower()
    allowed = settings.sso_allowed_domains_list
    if domain not in allowed:
        logger.info("sso domain rejected: %s (allowed=%s)", domain, allowed)
        return RedirectResponse(
            _frontend_login_error_url("domain_forbidden"), status_code=302
        )

    # Upsert user keyed by lowercased email.
    email_lower = email.lower()
    result = await db.execute(select(User).where(User.email == email_lower))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=email_lower,
            name=name,
            password_hash=None,  # SSO-only — no bcrypt hash.
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=False,
            oauth_provider="microsoft",
            external_id=azure_oid,
            azure_oid=azure_oid,
            microsoft_upn=email,
        )
        db.add(user)
    else:
        # Existing email/password user logging in via SSO for the first time:
        # link identity but DO NOT touch role / password_hash / profile_completed.
        user.oauth_provider = "microsoft"
        user.external_id = azure_oid
        user.azure_oid = azure_oid
        user.microsoft_upn = email
        if not user.is_active:
            return RedirectResponse(
                _frontend_login_error_url("Account disabled"), status_code=302
            )
    await db.flush()
    user_id = user.id

    # Issue Nexus JWTs.
    access = create_access_token(
        user.id,
        user.role.value,
        force_password_change=user.force_password_change,
    )
    refresh = create_refresh_token(user.id)

    # Stash behind a short-lived UUID (frontend will POST it back).
    exchange_code = secrets.token_urlsafe(40)
    db.add(
        AuthExchangeCode(
            code=exchange_code,
            user_id=user_id,
            access_token=access,
            refresh_token=refresh,
            expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=_EXCHANGE_TTL_SECONDS),
            consumed_at=None,
            created_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    return RedirectResponse(_frontend_callback_url(code=exchange_code), status_code=302)


@router.post("/exchange", response_model=ExchangeResponse)
@limiter.limit("5/minute")
async def exchange(
    request: Request,
    payload: ExchangeRequest = Body(...),
    db: AsyncSession = Depends(get_db),
) -> ExchangeResponse:
    """Trade the one-time UUID code for the real Nexus JWTs."""
    row = await db.scalar(
        select(AuthExchangeCode).where(AuthExchangeCode.code == payload.code)
    )
    if row is None:
        raise HTTPException(
            status.HTTP_410_GONE, detail="Exchange code unknown or already consumed"
        )
    now = datetime.now(timezone.utc)
    if row.consumed_at is not None or row.expires_at <= now:
        raise HTTPException(
            status.HTTP_410_GONE, detail="Exchange code expired or already consumed"
        )

    row.consumed_at = now
    user = await db.scalar(select(User).where(User.id == row.user_id))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="User no longer active")

    access = row.access_token
    refresh = row.refresh_token
    summary = SsoUserSummary(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role.value,
        profile_completed=user.profile_completed,
    )
    await db.commit()
    return ExchangeResponse(access_token=access, refresh_token=refresh, user=summary)
