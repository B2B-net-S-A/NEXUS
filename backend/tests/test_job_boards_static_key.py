"""Statyczny klucz API JustJoin.IT / RocketJobs (rekomendacja dostawcy, 29.09.2026).

- klucz z env zastępuje połączenie OAuth: portal jest „ready” bez
  ``JJIT_OAUTH_*`` i bez wiersza połączenia;
- 401 po kluczu = ``PortalReconnectRequired`` (klucza nie da się odświeżyć);
- data ważności z ``exp`` (tylko do wyświetlenia) i ostrzeżenie 30 dni przed;
- jednostka z ``/organizations/units``, zapamiętana per klucz — nowy klucz
  czyta ją od nowa.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.job_board_connection import PROVIDER_JJIT, JobBoardConnection
from app.models.job_posting import Portal
from app.services import job_portals
from app.services.job_portals import jjit_connection
from app.services.job_portals.base import PortalConfig, PortalReconnectRequired
from app.services.job_portals.jjit_client import JjitApi

pytestmark = pytest.mark.asyncio


def _key(expires_in: timedelta) -> str:
    exp = datetime.now(timezone.utc) + expires_in
    # Podpis nieważny dla nas — NEXUS czyta `exp` bez weryfikacji.
    return jwt.encode({"sub": "u", "exp": int(exp.timestamp())}, "x", "HS256")


@pytest.fixture(autouse=True)
def static_key(monkeypatch):
    monkeypatch.setattr(settings, "JJIT_STATIC_ACCESS_TOKEN", _key(timedelta(days=700)))
    monkeypatch.setattr(settings, "JJIT_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr(settings, "JJIT_OAUTH_CLIENT_SECRET", "")
    monkeypatch.setattr(settings, "JJIT_OAUTH_REDIRECT_URI", "")
    monkeypatch.setattr(settings, "PORTAL_JJIT_API_URL", "https://api.test")
    monkeypatch.setattr(settings, "PORTAL_JJIT_ENABLED", True)
    monkeypatch.setattr(settings, "PORTAL_ROCKETJOBS_ENABLED", True)
    monkeypatch.setattr(settings, "PORTAL_JJIT_ORGANIZATION_UNIT_ID", "")
    monkeypatch.setattr(settings, "PORTAL_ROCKETJOBS_ORGANIZATION_UNIT_ID", "")


@pytest_asyncio.fixture
async def clean():
    async def wipe() -> None:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(JobBoardConnection).where(
                    JobBoardConnection.provider == PROVIDER_JJIT
                )
            )
            await db.execute(
                delete(AppSetting).where(
                    AppSetting.key == jjit_connection.STATIC_UNITS_KEY
                )
            )
            await db.commit()

    await wipe()
    yield
    await wipe()


def test_static_key_makes_the_portal_ready_without_oauth():
    config = PortalConfig.from_settings(Portal.rocketjobs)
    assert config.missing == ()
    assert config.needs_connection is False
    assert config.state == "ready"
    assert jjit_connection.auth_mode() == "static"


async def test_static_key_needs_no_connection_row(clean):
    async with AsyncSessionLocal() as db:
        config = PortalConfig.from_settings(Portal.justjoinit)
        assert await job_portals.resolve_state(db, config) == "ready"


async def test_access_token_returns_the_key_and_401_means_new_key():
    assert await jjit_connection.access_token() == settings.JJIT_STATIC_ACCESS_TOKEN
    with pytest.raises(PortalReconnectRequired) as exc:
        await jjit_connection.access_token(force_refresh=True)
    assert "klucz" in exc.value.message


def test_expiry_is_read_from_the_key(monkeypatch):
    expires = jjit_connection.static_token_expires_at()
    assert expires is not None
    assert expires > datetime.now(timezone.utc) + timedelta(days=600)
    assert jjit_connection.static_token_expiring() is False
    monkeypatch.setattr(settings, "JJIT_STATIC_ACCESS_TOKEN", _key(timedelta(days=10)))
    assert jjit_connection.static_token_expiring() is True
    # Klucz bez `exp` albo nie-JWT: brak daty, bez ostrzeżenia.
    monkeypatch.setattr(settings, "JJIT_STATIC_ACCESS_TOKEN", "opaque-key")
    assert jjit_connection.static_token_expires_at() is None
    assert jjit_connection.static_token_expiring() is False


def test_expiring_key_degrades_the_health_check():
    assert job_portals.health_state(0, reconnect_required=True) == "degraded"
    assert job_portals.health_state(0, connected=True) == "healthy"


async def test_unit_is_read_once_per_key(clean, monkeypatch):
    calls: list[int] = []

    async def units(self):
        calls.append(1)
        return [{"id": "unit-1", "organizationId": "org-1"}]

    monkeypatch.setattr(JjitApi, "units", units)
    async with AsyncSessionLocal() as db:
        assert await jjit_connection.resolve_unit(db, "rocketjobs") == "unit-1"
        assert await jjit_connection.resolve_unit(db, "justjoinit") == "unit-1"
    assert calls == [1]

    # Nowy klucz (np. inne konto) = jednostka czytana od nowa.
    monkeypatch.setattr(settings, "JJIT_STATIC_ACCESS_TOKEN", _key(timedelta(days=5)))
    async with AsyncSessionLocal() as db:
        assert await jjit_connection.resolve_unit(db, "rocketjobs") == "unit-1"
    assert calls == [1, 1]


async def test_env_unit_override_wins_without_api_call(clean, monkeypatch):
    async def never(self):
        raise AssertionError("no units call expected")

    monkeypatch.setattr(JjitApi, "units", never)
    monkeypatch.setattr(settings, "PORTAL_ROCKETJOBS_ORGANIZATION_UNIT_ID", "rj-unit")
    async with AsyncSessionLocal() as db:
        assert await jjit_connection.resolve_unit(db, "rocketjobs") == "rj-unit"


async def test_several_units_without_override_are_not_guessed(clean, monkeypatch):
    async def units(self):
        return [{"id": "unit-1"}, {"id": "unit-2"}]

    monkeypatch.setattr(JjitApi, "units", units)
    async with AsyncSessionLocal() as db:
        assert await jjit_connection.resolve_unit(db, "rocketjobs") is None


async def test_health_inputs_in_static_mode(clean, monkeypatch):
    from app.services.job_portals.service import portal_health_inputs

    async with AsyncSessionLocal() as db:
        failed, reconnect, connected = await portal_health_inputs(db)
    assert (reconnect, connected) == (False, True)
    monkeypatch.setattr(settings, "JJIT_STATIC_ACCESS_TOKEN", _key(timedelta(days=3)))
    async with AsyncSessionLocal() as db:
        _failed, reconnect, _connected = await portal_health_inputs(db)
    assert reconnect is True
