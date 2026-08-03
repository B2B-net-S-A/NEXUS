"""Tests for Microsoft SSO login (Faza B).

Strategy: mock the outbound call to ``login.microsoftonline.com`` via
monkeypatching :func:`app.api.auth_microsoft._exchange_code_for_id_token`.
We never make real HTTP requests — all id_token claims are injected.

Covers:
- ``authorize`` returns a URL that contains the configured client_id, the
  login redirect URI, and a state JWT with ``purpose=sso_login``.
- State JWT signing/verification rejects wrong purpose (mailbox state cannot
  replay on login flow).
- ``callback`` rejects domains outside ``SSO_ALLOWED_DOMAINS``.
- ``callback`` bootstraps a new allowed-domain user as Recruiter behind
  mandatory onboarding; an enabled AAD mapping remains authoritative,
  and stores an exchange-code row.
- ``callback`` for an existing email/password user links identity but does not
  touch role / password_hash / profile_completed.
- ``exchange`` consumes the code once; second use returns 410.
- ``exchange`` rejects expired codes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt as jose_jwt
from sqlalchemy import delete, select

from app.api import auth_microsoft as auth_ms_module
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.rate_limit import limiter as _limiter
from app.core.security import (
    ALGORITHM,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
)
from app.models.activity import Activity
from app.models.auth_exchange_code import AuthExchangeCode
from app.models.user import User, UserRole


@pytest.fixture(autouse=True)
def _disable_rate_limits():
    """Tests log in/out repeatedly — bypass slowapi caps."""
    _limiter.enabled = False
    yield
    _limiter.enabled = True


@pytest.fixture(autouse=True)
def _force_sso_config(monkeypatch):
    """Make sure SSO config looks valid regardless of dev .env."""
    monkeypatch.setattr(settings, "M365_INTEGRATION_ENABLED", True)
    monkeypatch.setattr(settings, "M365_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "M365_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(settings, "M365_TENANT_ID", "test-tenant-id")
    monkeypatch.setattr(
        settings,
        "MICROSOFT_LOGIN_REDIRECT_URI",
        "https://api.test.example/api/auth/microsoft/callback",
    )
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "b2bnetwork.pl")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://app.test.example")
    monkeypatch.setattr(
        settings,
        "M365_STATE_SIGNING_KEY",
        "test-state-key-at-least-48-chars-1234567890abcdefXYZ",
    )
    # AAD RBAC tests opt-in explicitly — keep the legacy path active by default
    # so the pre-7.2 test suite doesn't accidentally trip the new code.
    monkeypatch.setattr(settings, "AAD_GROUP_RBAC_ENABLED", False)
    monkeypatch.setattr(settings, "AAD_GROUP_ROLE_MAP_JSON", "")


@pytest_asyncio.fixture
async def app_client_no_redirect() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as c:
        yield c


@pytest_asyncio.fixture
async def cleanup_sso_users():
    """Track emails created during a test so we can clean them up."""
    created_emails: list[str] = []
    yield created_emails
    if not created_emails:
        return
    async with AsyncSessionLocal() as db:
        # Delete child rows referencing these users first. FKs on
        # auth_exchange_codes + activities both lack ON DELETE CASCADE, so
        # the application-side audit row that the SSO callback writes
        # (`Activity` for the login event) blocks the User delete otherwise.
        users = (
            await db.execute(select(User.id).where(User.email.in_(created_emails)))
        ).all()
        if users:
            ids = [r[0] for r in users]
            await db.execute(
                delete(AuthExchangeCode).where(AuthExchangeCode.user_id.in_(ids))
            )
            await db.execute(delete(Activity).where(Activity.user_id.in_(ids)))
        await db.execute(delete(User).where(User.email.in_(created_emails)))
        await db.commit()


# ── /authorize ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_authorize_returns_url_with_login_redirect(
    app_client_no_redirect: AsyncClient,
):
    resp = await app_client_no_redirect.get("/api/auth/microsoft/authorize")
    assert resp.status_code == 200, resp.text
    url = resp.json()["authorize_url"]
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    assert "login.microsoftonline.com" in parsed.netloc
    assert qs["client_id"] == ["test-client-id"]
    # redirect_uri now follows the app domain (PUBLIC_BASE_URL), not the legacy
    # MICROSOFT_LOGIN_REDIRECT_URI value — the OAuth hop must land on the app
    # host (api.nexus.* was Safe-Browsing-flagged); the frontend proxies it.
    assert qs["redirect_uri"] == ["https://app.test.example/auth/microsoft/callback"]
    assert "openid" in qs["scope"][0]
    assert "User.Read" in qs["scope"][0]
    # State JWT decodes to purpose=sso_login.
    state = qs["state"][0]
    pkce = auth_ms_module._verify_login_state(state)
    assert isinstance(pkce, str) and len(pkce) > 30


def test_state_jwt_rejects_wrong_purpose(monkeypatch):
    """Mailbox-state cannot replay as login-state and vice versa."""
    from app.services.m365 import oauth as m365_oauth

    # Build a mailbox-flow state (purpose="m365_oauth_state").
    verifier, _ = m365_oauth.generate_pkce_pair()
    mailbox_state = m365_oauth.sign_state(user_id=1, pkce_verifier=verifier)
    with pytest.raises(Exception):
        auth_ms_module._verify_login_state(mailbox_state)


# ── /callback ───────────────────────────────────────────────────────────────


def _make_state(verifier: str) -> str:
    return auth_ms_module._sign_login_state(verifier)


def _patch_token_exchange(monkeypatch, claims: dict, *, access_token: str = ""):
    """Stub the OAuth code exchange.

    The real function now returns ``{"claims": <id_token>, "access_token": ...}``
    after Phase 7.2; pre-7.2 callers only cared about claims so we keep the
    helper signature backwards-compatible by defaulting access_token to "".
    """

    async def _fake(_code: str, _verifier: str) -> dict:
        return {"claims": claims, "access_token": access_token}

    monkeypatch.setattr(auth_ms_module, "_exchange_code_for_id_token", _fake)


@pytest.mark.asyncio
async def test_callback_rejects_domain_not_in_whitelist(
    app_client_no_redirect: AsyncClient, monkeypatch, cleanup_sso_users
):
    _patch_token_exchange(
        monkeypatch,
        {
            "preferred_username": "intruder@gmail.com",
            "oid": "azure-oid-intruder",
            "name": "Intruder",
        },
    )
    state = _make_state("v" * 64)
    resp = await app_client_no_redirect.get(
        "/api/auth/microsoft/callback",
        params={"code": "any-code", "state": state},
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "/login?" in location and "domain_forbidden" in location

    # No user was created.
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == "intruder@gmail.com"))
        assert u is None


@pytest.mark.asyncio
async def test_callback_creates_new_sso_user_as_onboarding_recruiter(
    app_client_no_redirect: AsyncClient, monkeypatch, cleanup_sso_users
):
    unique = uuid.uuid4().hex[:8]
    email = f"new-sso-{unique}@b2bnetwork.pl"
    cleanup_sso_users.append(email)

    _patch_token_exchange(
        monkeypatch,
        {
            "preferred_username": email,
            "oid": f"azure-oid-{unique}",
            "name": "New SSO User",
            "email": email,
        },
    )
    state = _make_state("v" * 64)
    resp = await app_client_no_redirect.get(
        "/api/auth/microsoft/callback",
        params={"code": "graph-code", "state": state},
    )
    assert resp.status_code == 302
    location = resp.headers["location"]
    parsed = urlparse(location)
    assert parsed.path == "/login/microsoft/callback"
    qs = parse_qs(parsed.query)
    exchange_code = qs["code"][0]
    assert len(exchange_code) >= 40

    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        assert u is not None
        assert u.password_hash is None
        # New-user contract: allowlisted SSO identities become Recruiters but
        # cannot reach domain surfaces until mandatory onboarding completes.
        assert u.role == UserRole.recruiter
        assert u.roles == [UserRole.recruiter.value]
        assert u.is_active is True
        assert u.profile_completed is False
        assert u.oauth_provider == "microsoft"
        assert u.azure_oid == f"azure-oid-{unique}"
        assert u.microsoft_upn == email

        # Exchange code persisted, not yet consumed.
        ex = await db.scalar(
            select(AuthExchangeCode).where(AuthExchangeCode.code == exchange_code)
        )
        assert ex is not None
        assert ex.consumed_at is None
        assert ex.issued_authorization_version == u.authorization_version
        assert ex.expires_at > datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_callback_links_identity_for_existing_password_user(
    app_client_no_redirect: AsyncClient, monkeypatch, cleanup_sso_users
):
    """Existing email/password user: SSO links identity, leaves role/password intact."""
    unique = uuid.uuid4().hex[:8]
    email = f"existing-{unique}@b2bnetwork.pl"
    original_hash = hash_password("OriginalPasswordX1")
    cleanup_sso_users.append(email)

    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=original_hash,
                name="Existing Admin",
                role=UserRole.admin,
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()

    _patch_token_exchange(
        monkeypatch,
        {
            "preferred_username": email,
            "oid": f"azure-oid-existing-{unique}",
            "name": "Existing Admin",
            "email": email,
        },
    )
    state = _make_state("v" * 64)
    resp = await app_client_no_redirect.get(
        "/api/auth/microsoft/callback",
        params={"code": "graph-code", "state": state},
    )
    assert resp.status_code == 302

    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        assert u is not None
        # Role / hash / onboarding unchanged.
        assert u.role == UserRole.admin
        assert u.password_hash == original_hash
        assert u.profile_completed is True
        # Identity attached.
        assert u.oauth_provider == "microsoft"
        assert u.azure_oid == f"azure-oid-existing-{unique}"


@pytest.mark.asyncio
async def test_callback_with_invalid_state_redirects_to_login(
    app_client_no_redirect: AsyncClient, monkeypatch
):
    resp = await app_client_no_redirect.get(
        "/api/auth/microsoft/callback",
        params={"code": "graph-code", "state": "not-a-jwt"},
    )
    assert resp.status_code == 302
    assert "/login?" in resp.headers["location"]
    assert "error=" in resp.headers["location"]


# ── /exchange ───────────────────────────────────────────────────────────────


def _exchange_token_pair(user_id: int, authorization_version: int) -> tuple[str, str]:
    return (
        create_access_token(
            user_id,
            UserRole.recruiter.value,
            roles=[UserRole.recruiter.value],
            authorization_version=authorization_version,
        ),
        create_refresh_token(
            user_id,
            authorization_version=authorization_version,
        ),
    )


def test_exchange_token_pair_accepts_current_authorization_version():
    access, refresh = _exchange_token_pair(41, 7)

    assert auth_ms_module._exchange_tokens_are_current(
        access,
        refresh,
        user_id=41,
        authorization_version=7,
        tokens_valid_after=None,
    )


def test_exchange_token_pair_rejects_stale_authorization_version():
    access, refresh = _exchange_token_pair(41, 6)

    assert not auth_ms_module._exchange_tokens_are_current(
        access,
        refresh,
        user_id=41,
        authorization_version=7,
        tokens_valid_after=None,
    )


def test_exchange_token_pair_rejects_missing_authorization_version():
    access, refresh = _exchange_token_pair(41, 7)
    access_payload = decode_token(access)
    access_payload.pop("av")
    access_without_av = jose_jwt.encode(
        access_payload,
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )

    assert not auth_ms_module._exchange_tokens_are_current(
        access_without_av,
        refresh,
        user_id=41,
        authorization_version=7,
        tokens_valid_after=None,
    )


async def _make_exchange_row(
    user_id: int,
    *,
    expires_in_seconds: int = 60,
    consumed: bool = False,
    issued_authorization_version: int | None = None,
    token_authorization_version: int | None = None,
    omit_access_token_av: bool = False,
    omit_refresh_token_av: bool = False,
) -> str:
    code = uuid.uuid4().hex + uuid.uuid4().hex[:8]  # 40 chars
    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        assert user is not None
        issued_version = (
            user.authorization_version
            if issued_authorization_version is None
            else issued_authorization_version
        )
        token_version = (
            issued_version
            if token_authorization_version is None
            else token_authorization_version
        )
        access_token = create_access_token(
            user_id,
            user.role.value,
            roles=[role.value for role in user.get_all_roles()],
            authorization_version=token_version,
        )
        refresh_token = create_refresh_token(
            user_id,
            authorization_version=token_version,
        )
        if omit_access_token_av:
            access_payload = decode_token(access_token)
            access_payload.pop("av", None)
            access_token = jose_jwt.encode(
                access_payload,
                settings.SECRET_KEY,
                algorithm=ALGORITHM,
            )
        if omit_refresh_token_av:
            refresh_payload = decode_token(refresh_token)
            refresh_payload.pop("av", None)
            refresh_token = jose_jwt.encode(
                refresh_payload,
                settings.SECRET_KEY,
                algorithm=ALGORITHM,
            )
        db.add(
            AuthExchangeCode(
                code=code,
                user_id=user_id,
                access_token=access_token,
                refresh_token=refresh_token,
                issued_authorization_version=issued_version,
                expires_at=datetime.now(timezone.utc)
                + timedelta(seconds=expires_in_seconds),
                consumed_at=(datetime.now(timezone.utc) if consumed else None),
                created_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    return code


async def _make_test_user(email: str) -> int:
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=None,
            name="SSO Test",
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=False,
            oauth_provider="microsoft",
            external_id=f"oid-{uuid.uuid4().hex[:8]}",
            azure_oid=f"oid-{uuid.uuid4().hex[:8]}",
            microsoft_upn=email,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


@pytest.mark.asyncio
async def test_exchange_consumes_current_version_code_once(
    app_client_no_redirect: AsyncClient, cleanup_sso_users
):
    unique = uuid.uuid4().hex[:8]
    email = f"exchange-{unique}@b2bnetwork.pl"
    cleanup_sso_users.append(email)
    user_id = await _make_test_user(email)
    code = await _make_exchange_row(user_id)

    resp1 = await app_client_no_redirect.post(
        "/api/auth/microsoft/exchange", json={"code": code}
    )
    assert resp1.status_code == 200, resp1.text
    body = resp1.json()
    access_payload = decode_token(body["access_token"])
    refresh_payload = decode_token(body["refresh_token"])
    assert access_payload["av"] == 1
    assert access_payload["type"] == "access"
    assert refresh_payload["av"] == 1
    assert refresh_payload["type"] == "refresh"
    assert body["user"]["email"] == email
    assert body["user"]["role"] == "recruiter"
    assert body["user"]["profile_completed"] is False

    # Second use → 410.
    resp2 = await app_client_no_redirect.post(
        "/api/auth/microsoft/exchange", json={"code": code}
    )
    assert resp2.status_code == 410


@pytest.mark.asyncio
async def test_exchange_rejects_stale_issued_authorization_version(
    app_client_no_redirect: AsyncClient, cleanup_sso_users
):
    unique = uuid.uuid4().hex[:8]
    email = f"exchange-stale-issued-{unique}@b2bnetwork.pl"
    cleanup_sso_users.append(email)
    user_id = await _make_test_user(email)
    code = await _make_exchange_row(user_id)

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.authorization_version += 1
        await db.commit()

    resp = await app_client_no_redirect.post(
        "/api/auth/microsoft/exchange", json={"code": code}
    )
    assert resp.status_code == 410
    async with AsyncSessionLocal() as db:
        assert await db.get(AuthExchangeCode, code) is None


@pytest.mark.asyncio
async def test_exchange_rejects_stale_token_authorization_version(
    app_client_no_redirect: AsyncClient, cleanup_sso_users
):
    unique = uuid.uuid4().hex[:8]
    email = f"exchange-stale-token-{unique}@b2bnetwork.pl"
    cleanup_sso_users.append(email)
    user_id = await _make_test_user(email)
    code = await _make_exchange_row(
        user_id,
        issued_authorization_version=1,
        token_authorization_version=0,
    )

    resp = await app_client_no_redirect.post(
        "/api/auth/microsoft/exchange", json={"code": code}
    )
    assert resp.status_code == 410
    async with AsyncSessionLocal() as db:
        assert await db.get(AuthExchangeCode, code) is None


@pytest.mark.asyncio
async def test_exchange_rejects_token_missing_authorization_version(
    app_client_no_redirect: AsyncClient, cleanup_sso_users
):
    unique = uuid.uuid4().hex[:8]
    email = f"exchange-missing-av-{unique}@b2bnetwork.pl"
    cleanup_sso_users.append(email)
    user_id = await _make_test_user(email)
    code = await _make_exchange_row(user_id, omit_access_token_av=True)

    resp = await app_client_no_redirect.post(
        "/api/auth/microsoft/exchange", json={"code": code}
    )
    assert resp.status_code == 410
    async with AsyncSessionLocal() as db:
        assert await db.get(AuthExchangeCode, code) is None


@pytest.mark.asyncio
async def test_exchange_rejects_expired_code(
    app_client_no_redirect: AsyncClient, cleanup_sso_users
):
    unique = uuid.uuid4().hex[:8]
    email = f"expired-{unique}@b2bnetwork.pl"
    cleanup_sso_users.append(email)
    user_id = await _make_test_user(email)
    code = await _make_exchange_row(user_id, expires_in_seconds=-1)

    resp = await app_client_no_redirect.post(
        "/api/auth/microsoft/exchange", json={"code": code}
    )
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_exchange_rejects_unknown_code(
    app_client_no_redirect: AsyncClient,
):
    resp = await app_client_no_redirect.post(
        "/api/auth/microsoft/exchange",
        json={"code": "x" * 40},
    )
    assert resp.status_code == 410
