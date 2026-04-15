"""
Test fixtures for DynaMinds ATS.
Uses the running backend API (localhost:8000) for integration tests.
"""
import pytest
import pytest_asyncio
from httpx import AsyncClient

BASE_URL = "http://localhost:8000"
TEST_EMAIL = "artur@b2bnet.pl"
TEST_PASSWORD = "admin123"


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(base_url=BASE_URL) as c:
        yield c


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient):
    """Login and return auth headers."""
    resp = await client.post("/api/auth/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
