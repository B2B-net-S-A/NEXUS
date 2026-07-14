"""Negative security contracts for staged browser cookie sessions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse, Response
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.csrf import CookieCSRFMiddleware
from app.core.security import decode_token, token_version_matches
from app.core.session import (
    ACCESS_COOKIE_NAME,
    CSRF_COOKIE_NAME,
    REFRESH_COOKIE_NAME,
    set_browser_session,
)


def test_session_cookies_are_secure_http_only_and_versioned(monkeypatch):
    monkeypatch.setattr(settings, "SESSION_COOKIE_DOMAIN", ".nexus.dynaminds.pl")
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", True)
    user = SimpleNamespace(
        id=42,
        role=SimpleNamespace(value="admin"),
        token_version=7,
        force_password_change=False,
    )
    response = Response()

    set_browser_session(response, user)

    cookies = response.headers.getlist("set-cookie")
    access = next(
        value for value in cookies if value.startswith(f"{ACCESS_COOKIE_NAME}=")
    )
    refresh = next(
        value for value in cookies if value.startswith(f"{REFRESH_COOKIE_NAME}=")
    )
    csrf = next(value for value in cookies if value.startswith(f"{CSRF_COOKIE_NAME}="))
    for value in (access, refresh):
        assert "HttpOnly" in value
        assert "Secure" in value
        assert "SameSite=lax" in value
        assert "Domain=.nexus.dynaminds.pl" in value
    assert "HttpOnly" not in csrf
    assert "Secure" in csrf
    assert "SameSite=lax" in csrf

    access_token = access.split(";", 1)[0].split("=", 1)[1]
    refresh_token = refresh.split(";", 1)[0].split("=", 1)[1]
    assert decode_token(access_token)["ver"] == 7
    assert decode_token(refresh_token)["ver"] == 7


def test_token_version_legacy_window_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "JWT_ALLOW_LEGACY_VERSIONLESS", True)
    assert token_version_matches({}, 0) is True
    assert token_version_matches({}, 1) is False
    assert token_version_matches({"ver": 2}, 2) is True
    assert token_version_matches({"ver": 1}, 2) is False
    assert token_version_matches({"ver": True}, 1) is False

    monkeypatch.setattr(settings, "JWT_ALLOW_LEGACY_VERSIONLESS", False)
    assert token_version_matches({}, 0) is False


def _csrf_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CookieCSRFMiddleware)

    @app.post("/write")
    async def write():
        return JSONResponse({"ok": True})

    @app.post("/api/auth/session/login")
    async def session_login():
        return JSONResponse({"ok": True})

    return app


@pytest.mark.asyncio
async def test_cookie_mutations_require_exact_origin_and_double_submit(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://nexus.dynaminds.pl"])
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://nexus.dynaminds.pl")
    transport = ASGITransport(app=_csrf_test_app())
    cookies = {ACCESS_COOKIE_NAME: "jwt", CSRF_COOKIE_NAME: "csrf-value"}
    async with AsyncClient(transport=transport, base_url="https://api.test") as client:
        missing = await client.post("/write", cookies=cookies)
        assert missing.status_code == 403
        assert missing.json()["detail"] == "csrf_origin_denied"

        hostile = await client.post(
            "/write",
            cookies=cookies,
            headers={
                "Origin": "https://evil.example",
                "X-CSRF-Token": "csrf-value",
            },
        )
        assert hostile.status_code == 403
        assert hostile.json()["detail"] == "csrf_origin_denied"

        mismatch = await client.post(
            "/write",
            cookies=cookies,
            headers={
                "Origin": "https://nexus.dynaminds.pl",
                "X-CSRF-Token": "wrong",
            },
        )
        assert mismatch.status_code == 403
        assert mismatch.json()["detail"] == "csrf_token_invalid"

        allowed = await client.post(
            "/write",
            cookies=cookies,
            headers={
                "Origin": "https://nexus.dynaminds.pl",
                "X-CSRF-Token": "csrf-value",
            },
        )
        assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_session_establishment_requires_exact_origin(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://nexus.dynaminds.pl"])
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://nexus.dynaminds.pl")
    transport = ASGITransport(app=_csrf_test_app())
    async with AsyncClient(transport=transport, base_url="https://api.test") as client:
        missing = await client.post("/api/auth/session/login")
        hostile = await client.post(
            "/api/auth/session/login",
            headers={"Origin": "https://evil.example"},
        )
        allowed = await client.post(
            "/api/auth/session/login",
            headers={"Origin": "https://nexus.dynaminds.pl"},
        )

    assert missing.status_code == 403
    assert hostile.status_code == 403
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_explicit_bearer_is_not_subject_to_cookie_csrf(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["https://nexus.dynaminds.pl"])
    transport = ASGITransport(app=_csrf_test_app())
    async with AsyncClient(transport=transport, base_url="https://api.test") as client:
        response = await client.post(
            "/write",
            cookies={ACCESS_COOKIE_NAME: "ambient-cookie"},
            headers={"Authorization": "Bearer explicit-client-token"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_web_login_has_no_token_body_and_logout_revokes_cookie(
    app_client: AsyncClient,
    monkeypatch,
):
    monkeypatch.setattr(settings, "SESSION_COOKIE_DOMAIN", "")
    monkeypatch.setattr(settings, "SESSION_COOKIE_SECURE", False)
    monkeypatch.setattr(settings, "CORS_ORIGINS", ["http://testserver"])
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "http://testserver")
    email = app_client.headers["X-Test-Admin-Email"]
    password = app_client.headers["X-Test-Admin-Password"]

    login = await app_client.post(
        "/api/auth/session/login",
        json={"email": email, "password": password},
        headers={"Origin": "http://testserver"},
    )
    assert login.status_code == 200, login.text
    assert "access_token" not in login.json()
    assert "refresh_token" not in login.json()
    access_cookie = login.cookies[ACCESS_COOKIE_NAME]
    csrf_cookie = login.cookies[CSRF_COOKIE_NAME]

    me = await app_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == email

    denied = await app_client.post("/api/auth/session/logout")
    assert denied.status_code == 403
    assert denied.json()["detail"] == "csrf_origin_denied"

    logout = await app_client.post(
        "/api/auth/session/logout",
        headers={
            "Origin": "http://testserver",
            "X-CSRF-Token": csrf_cookie,
        },
    )
    assert logout.status_code == 204

    stale = await app_client.get(
        "/api/auth/me",
        cookies={ACCESS_COOKIE_NAME: access_cookie},
    )
    assert stale.status_code == 401
