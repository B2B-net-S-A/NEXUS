"""
Test fixtures for Nexus ATS.

Two fixture families:
1. `client` + `auth_headers` — live-server fixtures (AsyncClient → localhost:8000).
   Used by the legacy integration tests in test_auth.py, test_candidates.py,
   test_contracts.py, test_dashboard.py, test_jobs.py, test_pipeline.py.
   These still require `uvicorn app.main:app` running on 8000.

2. `app_client` + `app_auth_headers` — in-process fixtures using
   httpx.ASGITransport(app=main.app). No network, runs in CI against the
   postgres service container. Used by Phase 7d+ integration tests.

Both share the DATABASE_URL env. In CI, alembic migrations run before pytest so
schema is ready.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


# Share one event loop across the whole session so asyncpg connection pools
# don't see the loop closing between tests.
@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


BASE_URL = "http://localhost:8000"


@pytest.fixture
def live_auth_credentials() -> dict[str, str]:
    """Credentials for an explicitly enabled local live-server test account."""
    email = os.environ.get("NEXUS_TEST_EMAIL", "")
    password = os.environ.get("NEXUS_TEST_PASSWORD", "")
    if not email or not password:
        pytest.skip("Set NEXUS_TEST_EMAIL and NEXUS_TEST_PASSWORD for live tests")
    return {"email": email, "password": password}


# ── Legacy live-server fixtures ─────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(base_url=BASE_URL) as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(
    client: AsyncClient, live_auth_credentials: dict[str, str]
) -> dict[str, str]:
    """Login and return auth headers (legacy live-server)."""
    resp = await client.post(
        "/api/auth/login",
        json=live_auth_credentials,
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ── In-process (Phase 7d) ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    """In-process FastAPI client — no running server required.

    Also seeds a test admin on first use (same event loop as client).
    Combined in one fixture to avoid 'attached to a different loop' errors
    from pytest-asyncio running each fixture in its own task.

    Disables slowapi rate limiting for tests so the 5/min login cap doesn't
    interfere with suites that login multiple times.
    """
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    # Disable in-process rate limits for the test session
    _limiter.enabled = False

    # Seed admin user in the same loop
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole
    from sqlalchemy import select

    unique = uuid.uuid4().hex[:8]
    # Use .example.com — always reserved for testing per RFC 2606
    email = f"pytest-admin-{unique}@example.com"
    password = f"T3st_{unique}!PassX"

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is None:
            u = User(
                email=email,
                password_hash=hash_password(password),
                name="Pytest Admin",
                role=UserRole.admin,
                is_active=True,
            )
            db.add(u)
            await db.commit()
            await db.refresh(u)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        # Expose credentials via extra headers attr for fixture consumers
        c.headers["X-Test-Admin-Email"] = email  # type: ignore[misc]
        c.headers["X-Test-Admin-Password"] = password  # type: ignore[misc]
        yield c


@pytest_asyncio.fixture
async def app_auth_headers(app_client: AsyncClient) -> dict[str, str]:
    """Log in the test admin via in-process client and return auth headers."""
    email = app_client.headers.get("X-Test-Admin-Email")
    password = app_client.headers.get("X-Test-Admin-Password")
    assert email and password, "admin_user was not seeded by app_client"

    resp = await app_client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# Skip live-server tests when RUN_LIVE_TESTS is not set
def pytest_collection_modifyitems(config, items):
    run_live = os.environ.get("RUN_LIVE_TESTS", "").lower() in ("1", "true", "yes")
    if run_live:
        return
    skip_live = pytest.mark.skip(
        reason="Live-server test; set RUN_LIVE_TESTS=1 to enable"
    )
    for item in items:
        # The legacy tests use `client` (not `app_client`)
        fixtures = getattr(item, "fixturenames", ())
        if "client" in fixtures and "app_client" not in fixtures:
            item.add_marker(skip_live)
