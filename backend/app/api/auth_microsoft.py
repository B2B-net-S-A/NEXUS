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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import create_access_token, create_refresh_token
from app.models.activity import Activity
from app.models.auth_exchange_code import AuthExchangeCode
from app.models.user import User, UserRole
from app.services.aad_role_policy import (
    InvalidAadRoleMapping,
    fail_closed_invalid_aad_mapping,
    validate_aad_mapped_roles,
)
from app.services.m365 import oauth as m365_oauth
from app.services.onboarding_access import onboarding_persona_changed

logger = logging.getLogger(__name__)

router = APIRouter()

# Login flow uses identity scopes only — separate from mailbox sync's
# Mail.* / Calendars.* scopes. ``offline_access`` keeps the refresh token in
# case we want to silently re-issue Nexus tokens later.
#
# Phase 7.2 footnote: ``GroupMember.Read.All`` is the scope used by AAD
# group-based RBAC. Microsoft classifies it as Delegated + admin-consent-
# required, so requesting it BEFORE the Azure AD app registration has
# admin consent granted breaks every fresh SSO login with
# AADSTS65001/65004. Requested dynamically by ``_login_scopes()`` only
# when ``AAD_GROUP_RBAC_ENABLED=true`` (operators flip it AFTER consent
# in Azure portal). Default deploys stay on the legacy 5-scope set.
_LOGIN_SCOPES_BASE = (
    "openid",
    "profile",
    "email",
    "User.Read",
    "offline_access",
)
_RBAC_SCOPE = "GroupMember.Read.All"


def _login_scopes() -> tuple[str, ...]:
    """Return the scope tuple for the next OAuth authorize/exchange call.

    Built per-call (not at import time) so toggling
    ``AAD_GROUP_RBAC_ENABLED`` in Coolify env vault picks up on the next
    request without a redeploy.
    """
    if settings.AAD_GROUP_RBAC_ENABLED:
        return _LOGIN_SCOPES_BASE + (_RBAC_SCOPE,)
    return _LOGIN_SCOPES_BASE


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


def is_sso_configured() -> bool:
    """Czy logowanie przez Microsoft jest w ogóle skonfigurowane.

    Używa tego publiczne ``GET /api/auth/methods``, żeby ekran logowania nie
    pokazywał przycisku, który i tak zwróci 503.

    Celowo pochodna :func:`_require_sso_configured`, a nie druga kopia tych
    samych warunków — dwie listy warunków rozjechałyby się przy pierwszej
    zmianie i ekran logowania zacząłby kłamać. Tamta funkcja zostaje przy
    rzucaniu wyjątków, bo jej komunikaty mówią KTÓREGO ustawienia brakuje.
    """
    try:
        _require_sso_configured()
    except HTTPException as exc:
        # Tylko 503 = „nie skonfigurowane". Każdy inny status oznacza, że
        # _require_sso_configured() zaczęło zgłaszać coś innego niż brak
        # konfiguracji — wtedy lepiej, żeby błąd wypłynął, niż żeby ekran
        # logowania po cichu ukrył przycisk Microsoft.
        if exc.status_code == status.HTTP_503_SERVICE_UNAVAILABLE:
            return False
        raise
    return True


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


def _login_redirect_uri() -> str:
    """OAuth ``redirect_uri`` for the SSO **login** flow.

    Derived from :data:`PUBLIC_BASE_URL` (the app domain) so Microsoft redirects
    the browser back to ``nexus.dynaminds.pl`` — NOT ``api.nexus.dynaminds.pl``.
    Google Safe Browsing false-flagged the api-host ``/microsoft/callback`` as a
    deceptive (Microsoft-impersonation) page and Chrome blocked every SSO login
    (2026-06-05). The frontend serves a thin proxy at the same path that forwards
    to this backend handler, so the browser never lands on the api subdomain.

    The path is ``/auth/microsoft/callback`` (NOT ``/api/auth/...``) on purpose:
    the shared Cloudflare zone Managed-Challenges any ``/api/auth/`` path, which
    would interject a "Just a moment" interstitial mid-OAuth. The frontend serves
    a thin proxy at ``/auth/microsoft/callback`` that forwards to this backend
    handler (still at ``/api/auth/microsoft/callback`` internally).

    NB: the legacy ``MICROSOFT_LOGIN_REDIRECT_URI`` env var still gates
    :func:`_require_sso_configured` (proof SSO is set up) but its *value* is no
    longer used to build the URL — the redirect target now follows the app
    domain. The old api-host URI and the new app-domain URI are both registered
    in Azure AD during the transition.
    """
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/auth/microsoft/callback"


def _build_authorize_url(state: str, pkce_verifier: str) -> str:
    challenge = m365_oauth._derive_challenge(pkce_verifier)
    tenant = settings.M365_TENANT_ID or "common"
    params = {
        "client_id": settings.M365_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": _login_redirect_uri(),
        "response_mode": "query",
        "scope": " ".join(_login_scopes()),
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
    """Trade authorization_code for id_token + access_token.

    Returns a dict with two keys:
        * ``claims``: decoded id_token claims (email, oid, name, ...).
        * ``access_token``: the Graph access_token, used by Phase 7.2 AAD
          group lookup. May be empty string if Microsoft omits it (should
          not happen for the requested scopes but we guard against it).

    Backwards-compat note: the function name and signature is preserved
    because :mod:`tests.test_auth_microsoft` monkeypatches it.
    """
    tenant = settings.M365_TENANT_ID or "common"
    data = {
        "client_id": settings.M365_CLIENT_ID,
        "client_secret": settings.M365_CLIENT_SECRET,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _login_redirect_uri(),
        "code_verifier": pkce_verifier,
        "scope": " ".join(_login_scopes()),
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
    return {
        "claims": m365_oauth._decode_id_token(id_token),
        "access_token": body.get("access_token") or "",
    }


def _frontend_callback_url(**params: str) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/login/microsoft/callback?{urlencode(params)}"


def _frontend_login_error_url(reason: str) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/login?{urlencode({'error': reason[:120]})}"


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/authorize", response_model=AuthorizeResponse)
# 60/min per IP (było 10). To endpoint klikany przyciskiem „Zaloguj się przez
# Microsoft" — buduje tylko URL, bez skutków ubocznych. Przy wspólnym kluczu
# limitu 10/min wystarczyło, że w tej samej minucie logowało się kilka osób,
# żeby reszta dostała 429 (zgłoszenie: Wiktoria Denka).
@limiter.limit("60/minute")
async def authorize(request: Request) -> AuthorizeResponse:
    """Build the Microsoft login URL. Frontend does ``window.location = url``."""
    _require_sso_configured()
    verifier, _ = m365_oauth.generate_pkce_pair()
    state = _sign_login_state(verifier)
    return AuthorizeResponse(authorize_url=_build_authorize_url(state, verifier))


@router.get("/callback", response_class=RedirectResponse)
# 60/min (było 20). Uwaga: tu NIE trafia przeglądarka, tylko serwerowy proxy
# z kontenera frontendu (app/auth/microsoft/callback/route.ts), więc bez
# przekazanego X-Forwarded-For wszyscy lądowaliby w jednym kubełku. Route
# handler forwarduje nagłówek — patrz komentarz tam.
@limiter.limit("60/minute")
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
        token_payload = await _exchange_code_for_id_token(code, pkce_verifier)
    except Exception as exc:  # noqa: BLE001
        logger.exception("sso code exchange failed")
        return RedirectResponse(
            _frontend_login_error_url(f"Token exchange failed: {exc!r}"),
            status_code=302,
        )

    claims = token_payload.get("claims") or {}
    graph_access_token = token_payload.get("access_token") or ""

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
        # First-time users from the verified corporate-domain allowlist enter
        # the Recruiter persona. They remain behind mandatory onboarding, and
        # an enabled AAD role mapping below stays authoritative and may replace
        # this bootstrap role before the first session is issued.
        user = User(
            email=email_lower,
            name=name,
            password_hash=None,  # SSO-only — no bcrypt hash.
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
            profile_completed=False,
            oauth_provider="microsoft",
            external_id=azure_oid,
            azure_oid=azure_oid,
            microsoft_upn=email,
        )
        db.add(user)
        # Security: log SSO auto-provisioning so admins have an audit trail
        # of new account creation. Domain whitelist already gates which
        # emails can self-provision, but recording WHO got created and when
        # is still needed for incident response (e.g. compromised corporate
        # MS account suddenly auto-provisioning into the ATS). Listing
        # placeholder user_id=0 (system action — no admin actor).
        await db.flush()  # populate user.id for the Activity FK
        logger.info(
            "sso new-user provisioned behind recruiter onboarding: "
            "email=%s domain=%s role=%s",
            email_lower,
            domain,
            UserRole.recruiter.value,
        )
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action="sso_user_provisioned",
                user_id=user.id,  # actor = the new user themselves (no admin involved)
                details={
                    "email": email_lower,
                    "domain": domain,
                    "provider": "microsoft",
                    "azure_oid": azure_oid,
                    "default_role": UserRole.recruiter.value,
                },
            )
        )
    else:
        # Existing email/password user logging in via SSO for the first time:
        # link identity but DO NOT touch role / password_hash / profile_completed.
        user.oauth_provider = "microsoft"
        user.external_id = azure_oid
        user.azure_oid = azure_oid
        user.microsoft_upn = email
        # When AAD RBAC is enabled, ``is_active`` is the AUTHORITATIVE output of
        # AAD group membership, re-derived in the RBAC block below (a user in a
        # valid group gets is_active=True; one in no mapped group gets blocked
        # with a clearer "no AD role" message). So a stale is_active=False — e.g.
        # left over from an admin bulk-cleanup that wrongly disabled an SSO
        # account — must NOT short-circuit here, or that user can never be
        # reactivated even while still in their AAD group. With RBAC disabled
        # there is no later gate, so the flag is honoured immediately.
        if not user.is_active and not settings.AAD_GROUP_RBAC_ENABLED:
            return RedirectResponse(
                _frontend_login_error_url("Account disabled"), status_code=302
            )

    # ── AAD group-based RBAC (Phase 7.2) ──────────────────────────────────
    # When enabled, the user's role + is_active flag are derived from their
    # AAD group membership, NOT from defaults / prior values. This is the
    # authoritative source: removing a user from the AAD admin group on
    # next login flips them to a lower role (or blocks them entirely).
    # Disabled by default for safety — flag flipped in Coolify env vault
    # only after AAD_GROUP_ROLE_MAP_JSON is populated and admin consent for
    # GroupMember.Read.All has been granted in the Azure app registration.
    if settings.AAD_GROUP_RBAC_ENABLED:
        from app.services.m365.aad_groups import (
            fetch_user_groups,
            map_groups_to_roles,
        )

        if not graph_access_token:
            logger.error(
                "sso callback: AAD RBAC enabled but Microsoft returned no "
                "access_token — check GroupMember.Read.All consent in Azure app."
            )
            return RedirectResponse(
                _frontend_login_error_url(
                    "AAD RBAC misconfigured (no Graph token). Contact administrator."
                ),
                status_code=302,
            )
        try:
            groups = await fetch_user_groups(graph_access_token)
        except Exception as exc:  # noqa: BLE001
            logger.exception("sso callback: AAD memberOf fetch failed")
            return RedirectResponse(
                _frontend_login_error_url(f"AAD group lookup failed: {exc!r}"[:120]),
                status_code=302,
            )

        # Keep the authoritative membership snapshot even when the role map is
        # malformed. The invalid-mapping branch commits it together with the
        # deactivation and audit record.
        user.aad_group_ids = groups
        try:
            mapping = settings.aad_group_role_map
        except ValueError as exc:
            logger.exception("sso callback: AAD_GROUP_ROLE_MAP_JSON invalid")
            await fail_closed_invalid_aad_mapping(
                db,
                user,
                actor_user_id=user.id,
                action="sso_aad_role_mapping_invalid",
                reason=str(exc),
                details={"aad_group_count": len(groups)},
            )
            return RedirectResponse(
                _frontend_login_error_url(
                    "AAD role mapping misconfigured. Contact administrator."
                ),
                status_code=302,
            )

        role_strs = map_groups_to_roles([g["id"] for g in groups], mapping)

        if not role_strs:
            # No NEXUS role granted by any AAD group → block login.
            # We also flip is_active=false so subsequent password-based
            # login attempts (if any password_hash still exists) also fail.
            if user.is_active:
                user.authorization_version += 1
                user.tokens_valid_after = datetime.now(timezone.utc)
            user.is_active = False
            await db.flush()
            db.add(
                Activity(
                    entity_type="user",
                    entity_id=user.id,
                    action="sso_aad_role_denied",
                    user_id=user.id,
                    details={
                        "email": email_lower,
                        "aad_group_count": len(groups),
                        "reason": "no AAD group matched AAD_GROUP_ROLE_MAP_JSON",
                    },
                )
            )
            await db.commit()
            return RedirectResponse(
                _frontend_login_error_url(
                    "Twoje konto nie ma przypisanej roli w Microsoft AD. "
                    "Skontaktuj sie z administratorem."
                ),
                status_code=302,
            )

        try:
            unique_role_strs, mapped_roles = validate_aad_mapped_roles(role_strs)
        except InvalidAadRoleMapping as exc:
            logger.error(
                "sso callback: invalid matched AAD roles=%s: %s",
                role_strs,
                exc,
            )
            await fail_closed_invalid_aad_mapping(
                db,
                user,
                actor_user_id=user.id,
                action="sso_aad_role_mapping_invalid",
                reason=str(exc),
                mapped_roles=role_strs,
                details={"aad_group_count": len(groups)},
            )
            return RedirectResponse(
                _frontend_login_error_url(
                    "AAD role mapping is invalid. Contact administrator."
                ),
                status_code=302,
            )

        # Multi-role assignment (migracja 0110): first match is primary
        # (writes ``users.role`` for legacy code), full ordered list is
        # written to ``users.roles``. Only audit primary-role transitions.
        role_strs = unique_role_strs
        new_role = mapped_roles[0]
        prior_roles = list(user.roles or [])
        onboarding_reset = onboarding_persona_changed(
            [role.value for role in user.get_all_roles()],
            role_strs,
        )
        legacy_sections_reset = new_role in {UserRole.finance, UserRole.user} and bool(
            user.allowed_sections
        )
        authorization_changed = (
            user.role != new_role
            or prior_roles != role_strs
            or not user.is_active
            or legacy_sections_reset
        )
        if user.role != new_role:
            db.add(
                Activity(
                    entity_type="user",
                    entity_id=user.id,
                    action="sso_aad_role_assigned",
                    user_id=user.id,
                    details={
                        "email": email_lower,
                        "from": user.role.value
                        if hasattr(user.role, "value")
                        else str(user.role),
                        "to": new_role.value,
                        "all_roles": role_strs,
                    },
                )
            )
            user.role = new_role
        if prior_roles != role_strs:
            db.add(
                Activity(
                    entity_type="user",
                    entity_id=user.id,
                    action="sso_aad_roles_updated",
                    user_id=user.id,
                    details={
                        "email": email_lower,
                        "from": prior_roles,
                        "to": role_strs,
                    },
                )
            )
            user.roles = role_strs
        if onboarding_reset:
            user.profile_completed = False
            user.profile_completed_at = None
        if new_role in {UserRole.finance, UserRole.user}:
            user.allowed_sections = []
        user.is_active = True
        if authorization_changed:
            user.authorization_version += 1
            user.tokens_valid_after = datetime.now(timezone.utc)

    # ``force_password_change`` is a PASSWORD-login concept: it gates the app to
    # make a user rotate an admin-set temporary password. A Microsoft SSO login
    # authenticates identity without touching any password, so this gate must
    # never block an SSO session — otherwise the user is trapped forever on the
    # "set new password" screen (change-password needs the old password; there is
    # no admin API to clear the flag). This applies REGARDLESS of ``password_hash``:
    # an admin ``reset-password`` sets a temp hash the SSO user never uses (that is
    # exactly the trap), so we must NOT gate on ``password_hash IS NULL``. A
    # successful SSO login satisfies the flag's intent → clear it. Users who log in
    # WITH a password still hit the gate normally (this code path is SSO-only).
    if user.force_password_change:
        user.force_password_change = False
        user.force_password_change_at = None

    await db.flush()
    user_id = user.id

    # Issue Nexus JWTs.
    access = create_access_token(
        user.id,
        user.role.value,
        force_password_change=user.force_password_change,
        roles=[r.value for r in user.get_all_roles()],
        authorization_version=user.authorization_version,
    )
    refresh = create_refresh_token(
        user.id, authorization_version=user.authorization_version
    )

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
# 60/min per IP (było 5). Wymiana jest sama w sobie ograniczona: kod jest
# jednorazowy i żyje 60 s, więc limit chroni tu przed zgadywaniem UUID-a, a nie
# przed wolumenem. 5/min przy wspólnym kluczu ucinało logowanie całemu biuru.
@limiter.limit("60/minute")
async def exchange(
    request: Request,
    payload: ExchangeRequest = Body(...),
    db: AsyncSession = Depends(get_db),
) -> ExchangeResponse:
    """Trade the one-time UUID code for the real Nexus JWTs."""
    now = datetime.now(timezone.utc)
    # Atomic consume: DELETE the row and take its contents in one statement.
    # Two wins over the previous read-then-stamp:
    #  1. `WHERE consumed_at IS NULL` makes consumption single-flight — two
    #     concurrent exchanges cannot both succeed (the loser deletes zero rows).
    #  2. DELETE (not stamp consumed_at) removes the plaintext access/refresh
    #     JWTs from the table the instant they are handed over. They were only
    #     ever needed for the ~60s handoff; keeping consumed rows around left a
    #     growing pile of live bearer tokens in cleartext at rest.
    consumed = (
        await db.execute(
            delete(AuthExchangeCode)
            .where(
                AuthExchangeCode.code == payload.code,
                AuthExchangeCode.consumed_at.is_(None),
                AuthExchangeCode.expires_at > now,
            )
            .returning(
                AuthExchangeCode.user_id,
                AuthExchangeCode.access_token,
                AuthExchangeCode.refresh_token,
            )
        )
    ).first()
    if consumed is None:
        raise HTTPException(
            status.HTTP_410_GONE,
            detail="Exchange code unknown, expired or already consumed",
        )
    user_id, access, refresh = consumed

    # Opportunistic cleanup: drop any codes that expired without being consumed,
    # so abandoned handoffs do not accumulate plaintext JWTs indefinitely.
    await db.execute(delete(AuthExchangeCode).where(AuthExchangeCode.expires_at <= now))

    user = await db.scalar(select(User).where(User.id == user_id))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="User no longer active")
    summary = SsoUserSummary(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role.value,
        profile_completed=user.profile_completed,
    )
    await db.commit()
    return ExchangeResponse(access_token=access, refresh_token=refresh, user=summary)
