"""Classic email+password login hardening (in-process).

Covers the two changes that move NEXUS to an email+password-only model:

1. ``SSO_ALLOWED_DOMAINS`` is now enforced on ``POST /api/auth/login`` (not just
   registration / the SSO callback). The check runs AFTER a correct password so
   it never leaks whether an account exists, and is FAIL-OPEN when the whitelist
   is empty so an unconfigured deploy cannot lock everyone out.

2. Microsoft SSO login is gated by the dedicated ``MICROSOFT_SSO_LOGIN_ENABLED``
   flag (default False), independent of ``M365_INTEGRATION_ENABLED`` — so the
   integration (calendar/Teams/mailbox) keeps running while interactive SSO
   login is off. ``_require_sso_configured()`` fails closed with 503.

Uses the in-process ``app_client`` fixture (runs in CI against the postgres
service container).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api import auth_microsoft
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole

ALLOWED_DOMAIN = "b2bnetwork.pl"
FOREIGN_DOMAIN = "outsider.example.org"
PASSWORD = "hunter2hunter"


def _unique_email(domain: str) -> str:
    return f"logintest-{uuid.uuid4().hex[:10]}@{domain}"


async def _seed_user(domain: str) -> str:
    """Create an active, email-verified email+password user; return the email."""
    email = _unique_email(domain)
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(PASSWORD),
                name="Login Test",
                role=UserRole.recruiter,
                roles=[UserRole.recruiter.value],
                is_active=True,
                email_verified=True,
            )
        )
        await db.commit()
    return email


@pytest.fixture
def whitelist_b2bnetwork(monkeypatch):
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", ALLOWED_DOMAIN)
    yield


@pytest.fixture
def whitelist_empty(monkeypatch):
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "")
    yield


# ── Domain whitelist on /login ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_allowed_domain_succeeds(
    app_client: AsyncClient, whitelist_b2bnetwork
):
    email = await _seed_user(ALLOWED_DOMAIN)
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]


@pytest.mark.asyncio
async def test_login_foreign_domain_forbidden(
    app_client: AsyncClient, whitelist_b2bnetwork
):
    """Correct password but a non-whitelisted domain → 403 (not 200, not 401)."""
    email = await _seed_user(FOREIGN_DOMAIN)
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 403, resp.text
    assert "domena" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_login_foreign_domain_wrong_password_is_401_not_403(
    app_client: AsyncClient, whitelist_b2bnetwork
):
    """No enumeration: a wrong password on a foreign-domain account still 401 —
    the domain 403 must only surface AFTER the password is verified."""
    email = await _seed_user(FOREIGN_DOMAIN)
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": "wrong-password"}
    )
    assert resp.status_code == 401, resp.text


@pytest.mark.asyncio
async def test_login_empty_whitelist_is_fail_open(
    app_client: AsyncClient, whitelist_empty
):
    """An unconfigured whitelist must NOT lock existing accounts out."""
    email = await _seed_user(FOREIGN_DOMAIN)
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text


# ── Microsoft SSO login kill-switch ──────────────────────────────────────────


def test_require_sso_configured_blocks_when_login_disabled(monkeypatch):
    """With MICROSOFT_SSO_LOGIN_ENABLED off, the SSO entry point fails closed."""
    monkeypatch.setattr(settings, "MICROSOFT_SSO_LOGIN_ENABLED", False)
    with pytest.raises(HTTPException) as exc:
        auth_microsoft._require_sso_configured()
    assert exc.value.status_code == 503
    assert "disabled" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_sso_login_disabled_by_default(app_client: AsyncClient):
    """Default deploy = email+password only. With MICROSOFT_SSO_LOGIN_ENABLED off
    (its default), the SSO authorize route fails closed with 503 (or 404 if the
    whole M365 integration is disabled). Never a working 200 in the default
    config — this test does NOT enable the flag on purpose."""
    resp = await app_client.get("/api/auth/microsoft/authorize")
    assert resp.status_code in (404, 503), resp.text


@pytest.mark.asyncio
async def test_sso_callback_disabled_redirects_to_login(app_client: AsyncClient):
    """/callback fails closed when SSO login is off — before any token exchange,
    user upsert, or JWT issuance. Browser landing page → 302 to /login (or 404 if
    the integration is disabled entirely). Does NOT enable the flag on purpose."""
    resp = await app_client.get(
        "/api/auth/microsoft/callback", params={"code": "x", "state": "y"}
    )
    assert resp.status_code in (302, 404), resp.text
    if resp.status_code == 302:
        assert "login" in resp.headers["location"].lower()


@pytest.mark.asyncio
async def test_sso_exchange_disabled_returns_503(app_client: AsyncClient):
    """/exchange fails closed when SSO login is off — before reading/consuming
    the exchange code, so no Nexus JWT is ever returned. Does NOT enable the
    flag on purpose."""
    resp = await app_client.post(
        "/api/auth/microsoft/exchange", json={"code": "x" * 40}
    )
    assert resp.status_code in (404, 503), resp.text
