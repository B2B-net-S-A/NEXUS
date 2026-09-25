"""Konto JustJoin.IT / RocketJobs (0381): OAuth, tokeny i callback.

- ``state`` podpisany i związany z celem (obcy JWT nie przejdzie);
- adres logowania niesie PKCE S256 i dane aplikacji;
- jednostka organizacyjna: env > claim z ``/oauth/me``;
- odświeżenie tokenu zapisuje nowy refresh token; ``invalid_grant`` =
  ``reconnect_required`` (zapisane mimo wyjątku);
- callback bez sesji NEXUSA: brak kodu / zły state / nie-admin = powrót
  z błędem, admin = zapis połączenia.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from jose import JWTError, jwt
from sqlalchemy import delete, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.encryption import TokenCipher
from app.models.job_board_connection import PROVIDER_JJIT, JobBoardConnection
from app.models.user import User, UserRole
from app.services.job_portals import jjit_connection
from app.services.job_portals.base import PortalReconnectRequired

pytestmark = pytest.mark.asyncio

CIPHER = TokenCipher(Fernet.generate_key().decode())


@pytest.fixture(autouse=True)
def oauth(monkeypatch):
    monkeypatch.setattr(settings, "JJIT_OAUTH_CLIENT_ID", "client-1")
    monkeypatch.setattr(settings, "JJIT_OAUTH_CLIENT_SECRET", "secret-1")
    monkeypatch.setattr(
        settings,
        "JJIT_OAUTH_REDIRECT_URI",
        "https://api.test/api/job-boards/jjit/callback",
    )
    monkeypatch.setattr(settings, "PORTAL_JJIT_ORGANIZATION_UNIT_ID", "")
    monkeypatch.setattr(settings, "PORTAL_ROCKETJOBS_ORGANIZATION_UNIT_ID", "")
    monkeypatch.setattr(jjit_connection, "get_token_cipher", lambda: CIPHER)


@pytest_asyncio.fixture
async def clean_connection():
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(JobBoardConnection).where(
                JobBoardConnection.provider == PROVIDER_JJIT
            )
        )
        await db.commit()
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(JobBoardConnection).where(
                JobBoardConnection.provider == PROVIDER_JJIT
            )
        )
        await db.commit()


def test_state_round_trip_and_foreign_purpose_is_rejected():
    token = jjit_connection.sign_state(42, "verifier")
    assert jjit_connection.verify_state(token) == (42, "verifier")
    foreign = jwt.encode(
        {
            "sub": "42",
            "pkce": "v",
            "purpose": "m365_oauth_state",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        settings.M365_STATE_SIGNING_KEY or settings.SECRET_KEY,
        algorithm="HS256",
    )
    with pytest.raises(JWTError):
        jjit_connection.verify_state(foreign)


def test_authorize_url_carries_pkce_and_app_data():
    url = urlparse(jjit_connection.authorize_url(7))
    query = parse_qs(url.query)
    assert url.path.endswith("/employer/oauth/authorize")
    assert query["client_id"] == ["client-1"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["response_type"] == ["code"]
    assert "offline_access" in query["scope"][0]
    assert jjit_connection.verify_state(query["state"][0])[0] == 7


def test_authorize_without_app_data_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "JJIT_OAUTH_CLIENT_SECRET", "")
    with pytest.raises(jjit_connection.ConnectionNotConfigured):
        jjit_connection.authorize_url(1)


def test_units_env_override_wins_over_claim(monkeypatch):
    assert jjit_connection.resolve_units({"organization_id": "org-1"}) == {
        "justjoinit": "org-1",
        "rocketjobs": "org-1",
    }
    monkeypatch.setattr(settings, "PORTAL_ROCKETJOBS_ORGANIZATION_UNIT_ID", "rj-unit")
    assert jjit_connection.resolve_units({})["rocketjobs"] == "rj-unit"
    assert "justjoinit" not in jjit_connection.resolve_units({})


async def _seed_connection(expires_in: timedelta) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            JobBoardConnection(
                provider=PROVIDER_JJIT,
                access_token_ct=CIPHER.encrypt("old-access"),
                refresh_token_ct=CIPHER.encrypt("old-refresh"),
                expires_at=datetime.now(timezone.utc) + expires_in,
                organization_units={"rocketjobs": "u-1"},
                connected_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def test_fresh_token_is_reused(clean_connection, monkeypatch):
    await _seed_connection(timedelta(hours=1))

    async def never(*_a, **_k):
        raise AssertionError("no refresh expected")

    monkeypatch.setattr(jjit_connection, "_token_request", never)
    assert await jjit_connection.access_token() == "old-access"


async def test_expired_token_is_refreshed_and_rotated(clean_connection, monkeypatch):
    await _seed_connection(timedelta(seconds=10))
    seen: list[dict] = []

    async def refresh(form, **_k):
        seen.append(form)
        return {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

    monkeypatch.setattr(jjit_connection, "_token_request", refresh)
    assert await jjit_connection.access_token() == "new-access"
    assert seen == [{"grant_type": "refresh_token", "refresh_token": "old-refresh"}]
    async with AsyncSessionLocal() as db:
        row = await jjit_connection.load(db)
        assert CIPHER.decrypt(row.refresh_token_ct) == "new-refresh"
        assert row.expires_at > datetime.now(timezone.utc) + timedelta(minutes=50)


async def test_invalid_grant_marks_reconnect_required(clean_connection, monkeypatch):
    await _seed_connection(timedelta(seconds=10))

    async def revoked(form, **_k):
        raise PortalReconnectRequired("Połączenie wygasło")

    monkeypatch.setattr(jjit_connection, "_token_request", revoked)
    with pytest.raises(PortalReconnectRequired):
        await jjit_connection.access_token()
    async with AsyncSessionLocal() as db:
        row = await jjit_connection.load(db)
        assert row.status == "reconnect_required"
        assert not await jjit_connection.is_connected(db)
    with pytest.raises(PortalReconnectRequired):
        await jjit_connection.access_token()


# ── Callback ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api() -> AsyncClient:
    from app.core.rate_limit import limiter
    from app.main import app

    limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


async def _user(role: UserRole) -> int:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"boards-{unique}@example.com",
            name=f"Konto {unique}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


def _status(resp) -> str:
    assert resp.status_code == 302, resp.text
    return parse_qs(urlparse(resp.headers["location"]).query)["status"][0]


async def test_callback_rejects_missing_code_and_bad_state(api):
    assert _status(await api.get("/api/job-boards/jjit/callback")) == "error"
    resp = await api.get("/api/job-boards/jjit/callback?code=x&state=nonsense")
    assert _status(resp) == "error"


async def test_callback_requires_admin(api, clean_connection, monkeypatch):
    recruiter = await _user(UserRole.recruiter)

    async def exchange(*_a, **_k):
        raise AssertionError("must not exchange for non-admin")

    monkeypatch.setattr(jjit_connection, "exchange_code", exchange)
    state = jjit_connection.sign_state(recruiter, "v")
    resp = await api.get(f"/api/job-boards/jjit/callback?code=c&state={state}")
    assert _status(resp) == "error"


async def test_callback_by_admin_stores_connection(api, clean_connection, monkeypatch):
    admin = await _user(UserRole.admin)
    captured: dict = {}

    async def exchange(db, *, code, verifier, user_id, transport=None):
        captured.update(code=code, verifier=verifier, user_id=user_id)
        row = JobBoardConnection(
            provider=PROVIDER_JJIT,
            refresh_token_ct=CIPHER.encrypt("r"),
            connected_at=datetime.now(timezone.utc),
            connected_by=user_id,
        )
        db.add(row)
        await db.flush()
        return row

    monkeypatch.setattr(jjit_connection, "exchange_code", exchange)
    state = jjit_connection.sign_state(admin, "the-verifier")
    resp = await api.get(f"/api/job-boards/jjit/callback?code=abc&state={state}")
    assert _status(resp) == "success"
    assert captured == {"code": "abc", "verifier": "the-verifier", "user_id": admin}
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobBoardConnection).where(
                JobBoardConnection.provider == PROVIDER_JJIT
            )
        )
        assert row is not None and row.connected_by == admin
