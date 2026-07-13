"""Tests for auth API — runs against live backend."""

from httpx import AsyncClient


async def test_login_success(
    client: AsyncClient, live_auth_credentials: dict[str, str]
):
    resp = await client.post("/api/auth/login", json=live_auth_credentials)
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(
    client: AsyncClient, live_auth_credentials: dict[str, str]
):
    resp = await client.post(
        "/api/auth/login",
        json={
            "email": live_auth_credentials["email"],
            "password": "wrong",
        },
    )
    assert resp.status_code == 401


async def test_login_nonexistent_user(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={
            "email": "nobody@test.pl",
            "password": "test123",
        },
    )
    assert resp.status_code == 401


async def test_me_authenticated(
    client: AsyncClient,
    auth_headers: dict,
    live_auth_credentials: dict[str, str],
):
    resp = await client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == live_auth_credentials["email"]
    assert "role" in data


async def test_me_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code in (401, 403)
