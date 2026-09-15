"""Password login — in-process client, own seeded user.

Ported from the live-server suite, which logged in as a hard-coded account on
a running backend. `/api/auth/me` cases are covered elsewhere:
authenticated → `test_api_integration.py::test_auth_me_with_token_ok`,
missing token → `test_auth_missing_credentials.py` (exact 401 contract).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

LOGIN = "/api/auth/login"


async def test_login_success(app_client: AsyncClient):
    email = app_client.headers["X-Test-Admin-Email"]
    password = app_client.headers["X-Test-Admin-Password"]
    resp = await app_client.post(LOGIN, json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"

    me = await app_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == email


async def test_login_wrong_password(app_client: AsyncClient):
    email = app_client.headers["X-Test-Admin-Email"]
    resp = await app_client.post(
        LOGIN, json={"email": email, "password": f"wrong-{uuid.uuid4().hex}"}
    )
    assert resp.status_code == 401
    assert "access_token" not in resp.json()


async def test_login_nonexistent_user(app_client: AsyncClient):
    resp = await app_client.post(
        LOGIN,
        json={
            "email": f"nobody-{uuid.uuid4().hex[:10]}@example.com",
            "password": "test123-Password!",
        },
    )
    assert resp.status_code == 401
