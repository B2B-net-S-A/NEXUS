"""Self-service registration + email-verification flow (in-process).

Covers POST /api/auth/register, /api/auth/verify-email, and the login
email_verified gate. Uses the in-process ``app_client`` fixture (runs in CI
against the postgres service container; alembic migration 0139 creates the
``email_verified`` column + ``email_verification_tokens`` table beforehand).

Security invariants under test:
- Endpoint gated by ``SELF_REGISTRATION_ENABLED`` (503 when off).
- Domain whitelist enforced (fail-closed).
- Role is ALWAYS forced to ``user`` — a caller-supplied ``role`` is ignored,
  so nobody can self-provision an ``admin``.
- Account is unverified and cannot log in until the email link is consumed.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.services.email_verification import create_verification_token

ALLOWED_DOMAIN = "example.com"


def _unique_email(domain: str = ALLOWED_DOMAIN) -> str:
    return f"selfreg-{uuid.uuid4().hex[:10]}@{domain}"


@pytest.fixture
def enable_registration(monkeypatch):
    """Turn self-registration ON and whitelist example.com for the test."""
    monkeypatch.setattr(settings, "SELF_REGISTRATION_ENABLED", True)
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", ALLOWED_DOMAIN)
    yield


async def _get_user(email: str) -> User | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User).where(User.email == email))


@pytest.mark.asyncio
async def test_register_disabled_returns_503(app_client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "SELF_REGISTRATION_ENABLED", False)
    resp = await app_client.post(
        "/api/auth/register",
        json={"name": "Jan", "email": _unique_email(), "password": "hunter2hunter"},
    )
    assert resp.status_code == 503, resp.text


@pytest.mark.asyncio
async def test_register_rejects_foreign_domain(
    app_client: AsyncClient, enable_registration
):
    resp = await app_client.post(
        "/api/auth/register",
        json={
            "name": "Mallory",
            "email": _unique_email("evil.example.org"),
            "password": "hunter2hunter",
        },
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"] == "domain_forbidden"


@pytest.mark.asyncio
async def test_register_creates_unverified_viewer(
    app_client: AsyncClient, enable_registration
):
    email = _unique_email()
    resp = await app_client.post(
        "/api/auth/register",
        json={"name": "Jan Kowalski", "email": email, "password": "hunter2hunter"},
    )
    assert resp.status_code == 201, resp.text

    user = await _get_user(email)
    assert user is not None
    assert user.role == UserRole.user
    assert user.roles == [UserRole.user.value]
    assert user.is_active is True
    assert user.email_verified is False
    assert user.password_hash  # bcrypt hash set


@pytest.mark.asyncio
async def test_register_ignores_caller_supplied_role(
    app_client: AsyncClient, enable_registration
):
    """A malicious ``role: admin`` in the body must NOT escalate privileges."""
    email = _unique_email()
    resp = await app_client.post(
        "/api/auth/register",
        json={
            "name": "Escalator",
            "email": email,
            "password": "hunter2hunter",
            "role": "admin",  # extra field — Pydantic ignores it
        },
    )
    assert resp.status_code == 201, resp.text
    user = await _get_user(email)
    assert user is not None
    assert user.role == UserRole.user  # NOT admin


@pytest.mark.asyncio
async def test_register_lowercases_email(app_client: AsyncClient, enable_registration):
    raw = f"MixedCase-{uuid.uuid4().hex[:8]}@{ALLOWED_DOMAIN}"
    resp = await app_client.post(
        "/api/auth/register",
        json={"name": "Case", "email": raw, "password": "hunter2hunter"},
    )
    assert resp.status_code == 201, resp.text
    assert await _get_user(raw.lower()) is not None


@pytest.mark.asyncio
async def test_register_duplicate_is_generic_201_no_enumeration(
    app_client: AsyncClient, enable_registration
):
    """Anti-enumeration: a duplicate registration returns the SAME generic 201
    as a fresh one (never 409), and does not create a second row or mutate the
    existing account."""
    email = _unique_email()
    body = {"name": "Jan", "email": email, "password": "hunter2hunter"}
    first = await app_client.post("/api/auth/register", json=body)
    assert first.status_code == 201, first.text

    second = await app_client.post("/api/auth/register", json=body)
    assert second.status_code == 201, second.text
    assert second.json()["detail"] == first.json()["detail"]

    # Exactly one row, still a read-only viewer (no escalation, no duplicate).
    async with AsyncSessionLocal() as db:
        rows = (
            (await db.execute(select(User).where(User.email == email))).scalars().all()
        )
    assert len(rows) == 1
    assert rows[0].role == UserRole.user


@pytest.mark.asyncio
async def test_register_short_password_rejected(
    app_client: AsyncClient, enable_registration
):
    resp = await app_client.post(
        "/api/auth/register",
        json={"name": "Jan", "email": _unique_email(), "password": "short"},
    )
    assert resp.status_code == 422, resp.text  # pydantic min_length=8


@pytest.mark.asyncio
async def test_login_blocked_until_verified(
    app_client: AsyncClient, enable_registration
):
    email = _unique_email()
    pwd = "hunter2hunter"
    reg = await app_client.post(
        "/api/auth/register", json={"name": "Jan", "email": email, "password": pwd}
    )
    assert reg.status_code == 201, reg.text

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": pwd}
    )
    assert login.status_code == 403, login.text
    assert "Potwierdź" in login.json()["detail"]


@pytest.mark.asyncio
async def test_verify_email_then_login_succeeds(
    app_client: AsyncClient, enable_registration
):
    email = _unique_email()
    pwd = "hunter2hunter"
    reg = await app_client.post(
        "/api/auth/register", json={"name": "Jan", "email": email, "password": pwd}
    )
    assert reg.status_code == 201, reg.text

    # Mint a known plaintext token for this user (invalidates the emailed one).
    user = await _get_user(email)
    assert user is not None
    async with AsyncSessionLocal() as db:
        token = await create_verification_token(db, user.id)
        await db.commit()

    verify = await app_client.post("/api/auth/verify-email", json={"token": token})
    assert verify.status_code == 204, verify.text

    refreshed = await _get_user(email)
    assert refreshed is not None and refreshed.email_verified is True

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": pwd}
    )
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]


@pytest.mark.asyncio
async def test_verify_email_invalid_token_400(app_client: AsyncClient):
    bogus = "f" * 64
    resp = await app_client.post("/api/auth/verify-email", json={"token": bogus})
    assert resp.status_code == 400, resp.text


@pytest.mark.asyncio
async def test_resend_verification_is_generic(
    app_client: AsyncClient, enable_registration
):
    """Always 200 regardless of whether the email exists (anti-enumeration)."""
    resp = await app_client.post(
        "/api/auth/resend-verification",
        json={"email": _unique_email()},  # never registered
    )
    assert resp.status_code == 200, resp.text
    assert "detail" in resp.json()
