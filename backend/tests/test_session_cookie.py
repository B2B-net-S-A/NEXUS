"""Sesja przeglądarki w ciasteczku HttpOnly + CSRF (``app/core/session_cookie``).

Część bez bazy sprawdza bramkę na minimalnej aplikacji: ciasteczko bez nagłówka
CSRF przy zapisie = 403 zanim cokolwiek dotknie bazy, Bearer omija CSRF.
Część z bazą (``app_client``) przechodzi logowanie: ciasteczko ``HttpOnly``,
odczyt samym ciasteczkiem, zapis bez nagłówka = 403, adopcja i wylogowanie.
"""

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.api.deps import get_current_user
from app.core import session_cookie
from app.core.config import settings
from app.core.database import get_db
from app.core.session_cookie import (
    CSRF_HEADER,
    SESSION_COOKIE_NAME,
    cookie_domain,
    request_bearer_token,
)
from app.models.user import User

FRONT = "https://nexus.example.test"


@pytest.fixture(autouse=True)
def _front_origin(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ORIGINS", [FRONT, "http://localhost:3100"])


def _request(
    host: str = "api.nexus.example.test",
    origin: str | None = FRONT,
    method: str = "GET",
    cookie: str | None = None,
    authorization: str | None = None,
) -> Request:
    headers = [(b"host", host.encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    if cookie:
        headers.append((b"cookie", f"{SESSION_COOKIE_NAME}={cookie}".encode()))
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "scheme": "https",
            "server": (host, 443),
            "path": "/",
            "query_string": b"",
            "headers": headers,
        }
    )


# ── domena ciasteczka ────────────────────────────────────────────────────────


def test_cookie_domain_is_front_host_when_api_is_its_subdomain():
    assert cookie_domain(_request()) == "nexus.example.test"


def test_cookie_domain_host_only_on_localhost_staging():
    req = _request(host="localhost:8100", origin="http://localhost:3100")
    assert cookie_domain(req) is None


def test_cookie_domain_ignores_foreign_origin():
    # Obca strona nie może wymusić ciasteczka na swojej domenie nadrzędnej.
    req = _request(host="api.nexus.example.test", origin="https://example.test")
    assert cookie_domain(req) is None


def test_request_bearer_token_prefers_header_then_cookie():
    assert request_bearer_token(_request(cookie="c", authorization="Bearer h")) == "h"
    assert request_bearer_token(_request(cookie="c")) == "c"
    assert request_bearer_token(_request()) is None


# ── bramka bez bazy ──────────────────────────────────────────────────────────


@pytest.fixture
def gate_app() -> FastAPI:
    app = FastAPI()

    @app.get("/protected")
    async def read(current_user: User = Depends(get_current_user)):
        return {"id": current_user.id}

    @app.post("/protected")
    async def write(current_user: User = Depends(get_current_user)):
        return {"id": current_user.id}

    async def _no_db():
        yield None

    app.dependency_overrides[get_db] = _no_db
    return app


@pytest.fixture
async def app_client(gate_app: FastAPI):
    async with AsyncClient(
        transport=ASGITransport(app=gate_app), base_url="https://api.nexus.example.test"
    ) as c:
        yield c


async def test_cookie_write_without_csrf_header_is_403(app_client):
    app_client.cookies.set(SESSION_COOKIE_NAME, "anything")
    r = await app_client.post("/protected", headers={"Origin": FRONT})
    assert r.status_code == 403
    assert r.json()["detail"] == session_cookie.CSRF_DENIED_DETAIL


async def test_cookie_write_from_foreign_origin_is_403(app_client):
    app_client.cookies.set(SESSION_COOKIE_NAME, "anything")
    r = await app_client.post(
        "/protected", headers={CSRF_HEADER: "1", "Origin": "https://evil.example"}
    )
    assert r.status_code == 403


async def test_cookie_write_without_origin_is_403(app_client):
    app_client.cookies.set(SESSION_COOKIE_NAME, "anything")
    r = await app_client.post("/protected", headers={CSRF_HEADER: "1"})
    assert r.status_code == 403


async def test_cookie_write_with_csrf_reaches_token_check(app_client):
    # Nagłówek i Origin w porządku → bramka CSRF przepuszcza, a zły token = 401.
    app_client.cookies.set(SESSION_COOKIE_NAME, "not-a-jwt")
    r = await app_client.post("/protected", headers={CSRF_HEADER: "1", "Origin": FRONT})
    assert r.status_code == 401


async def test_cookie_read_needs_no_csrf_header(app_client):
    app_client.cookies.set(SESSION_COOKIE_NAME, "not-a-jwt")
    r = await app_client.get("/protected")
    assert r.status_code == 401  # zły token, ale nie 403 z CSRF


async def test_bearer_write_skips_csrf(app_client):
    # Przeglądarka sama nie dokleja Authorization — CSRF go nie dotyczy.
    app_client.cookies.set(SESSION_COOKIE_NAME, "anything")
    r = await app_client.post(
        "/protected", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert r.status_code == 401


async def test_no_credentials_still_401(app_client):
    r = await app_client.post("/protected")
    assert r.status_code == 401


# ── pełna ścieżka na bazie ───────────────────────────────────────────────────


@pytest.fixture
async def https_app_client():
    """Klient in-process po HTTPS — ciasteczko jest ``Secure``.

    Konto admina zakłada fixture ``app_client`` z conftestu; tu potrzebny
    drugi klient z adresem https, bo słoik ciasteczek httpx nie odda
    ciasteczka ``Secure`` po http.
    """
    import uuid

    from app.core.database import AsyncSessionLocal
    from app.core.rate_limit import limiter
    from app.core.security import hash_password
    from app.main import app
    from app.models.user import UserRole

    limiter.enabled = False
    unique = uuid.uuid4().hex[:8]
    email = f"pytest-cookie-{unique}@example.com"
    password = f"T3st_{unique}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Pytest Cookie",
                role=UserRole.admin,
                is_active=True,
            )
        )
        await db.commit()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://api.nexus.example.test"
    ) as c:
        c.headers["X-Test-Email"] = email
        c.headers["X-Test-Password"] = password
        yield c


async def _login(c: AsyncClient):
    return await c.post(
        "/api/auth/login",
        json={
            "email": c.headers["X-Test-Email"],
            "password": c.headers["X-Test-Password"],
        },
        headers={"Origin": FRONT},
    )


async def test_login_sets_httponly_secure_lax_cookie(https_app_client):
    r = await _login(https_app_client)
    assert r.status_code == 200, r.text
    set_cookie = r.headers["set-cookie"]
    assert set_cookie.startswith(f"{SESSION_COOKIE_NAME}=")
    lowered = set_cookie.lower()
    assert "httponly" in lowered
    assert "secure" in lowered
    assert "samesite=lax" in lowered
    assert "domain=nexus.example.test" in lowered
    # Token w ciele zostaje dla dodatku Outlooka i skryptów.
    assert r.json()["access_token"]


async def test_cookie_alone_reads_me_and_write_needs_csrf(https_app_client):
    c = https_app_client
    assert (await _login(c)).status_code == 200
    me = await c.get("/api/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["email"] == c.headers["X-Test-Email"]

    body = {"current_password": "x" * 12, "new_password": "y" * 12}
    denied = await c.post("/api/auth/change-password", json=body)
    assert denied.status_code == 403
    allowed = await c.post(
        "/api/auth/change-password",
        json=body,
        headers={CSRF_HEADER: "1", "Origin": FRONT},
    )
    # Przeszło przez CSRF i uwierzytelnienie; złe obecne hasło = 400.
    assert allowed.status_code == 400


async def test_adopt_bearer_into_cookie_and_logout(https_app_client):
    c = https_app_client
    token = (await _login(c)).json()["access_token"]
    c.cookies.clear()
    assert (await c.get("/api/auth/me")).status_code == 401

    adopted = await c.post(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {token}", "Origin": FRONT},
    )
    assert adopted.status_code == 204
    assert "httponly" in adopted.headers["set-cookie"].lower()
    assert (await c.get("/api/auth/me")).status_code == 200

    out = await c.post("/api/auth/logout", headers={CSRF_HEADER: "1", "Origin": FRONT})
    assert out.status_code == 204
    assert "max-age=0" in out.headers["set-cookie"].lower()
    assert (await c.get("/api/auth/me")).status_code == 401


async def test_adopt_requires_bearer_header(https_app_client):
    c = https_app_client
    assert (await _login(c)).status_code == 200
    r = await c.post("/api/auth/session", headers={CSRF_HEADER: "1", "Origin": FRONT})
    assert r.status_code == 400
