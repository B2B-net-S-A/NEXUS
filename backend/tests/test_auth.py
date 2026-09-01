"""Tests for auth API — runs against live backend."""

import pytest
from httpx import AsyncClient


async def test_login_success(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={
            "email": "artur@b2bnet.pl",
            "password": "admin123",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(client: AsyncClient):
    resp = await client.post(
        "/api/auth/login",
        json={
            "email": "artur@b2bnet.pl",
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


async def test_me_authenticated(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "artur@b2bnet.pl"
    assert data["role"] == "admin"


async def test_me_unauthenticated(client: AsyncClient):
    # MUSI być dokładnie 401, nie „401 albo 403".
    # Frontend wylogowuje i przekierowuje na /login wyłącznie na 401
    # (frontend/src/lib/api.ts); 403 znaczy „jesteś zalogowany, ale nie wolno ci"
    # i celowo NIE wylogowuje. Gdy brak nagłówka Authorization zwracał 403,
    # wygasła sesja zostawiała użytkownika w powłoce aplikacji z widgetami
    # „Brak uprawnień do tego widoku" zamiast na ekranie logowania.
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
