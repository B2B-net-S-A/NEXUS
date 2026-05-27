"""CloudTalk API endpoint tests — verify error mapping after PR3.

Bug context: production Sentry NEXUS-BE-1S was emitting 502 for
CloudTalk auth-failure. 502 implies a downstream gateway problem,
but a 401 from CloudTalk means *our* credentials are wrong → 503
("integration not configured") fits the semantics better and stops
the alert noise.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from app.services.cloudtalk.client import CloudTalkAuthError, CloudTalkError


@pytest.mark.asyncio
async def test_agents_returns_503_when_disabled(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    monkeypatch.setattr("app.core.config.settings.CLOUDTALK_ENABLED", False)
    resp = await app_client.get("/api/cloudtalk/agents", headers=app_auth_headers)
    assert resp.status_code == 503
    assert "disabled" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_agents_auth_error_returns_503_not_502(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """CloudTalkAuthError (401 upstream) → 503, not 502.

    Before fix: Sentry NEXUS-BE-1S emitted 6× 502 alerts/hour because
    CLOUDTALK_API_KEY_ID/SECRET on prod were stale. 503 reframes this as
    "we're not configured" instead of "their gateway is broken".
    """
    monkeypatch.setattr("app.core.config.settings.CLOUDTALK_ENABLED", True)
    monkeypatch.setattr(
        "app.core.config.settings.CLOUDTALK_API_KEY_ID", "fake-id"
    )
    monkeypatch.setattr(
        "app.core.config.settings.CLOUDTALK_API_KEY_SECRET", "fake-secret"
    )

    with patch(
        "app.api.cloudtalk.CloudTalkClient.__aenter__",
        new_callable=AsyncMock,
    ) as enter_mock:
        client_mock = AsyncMock()
        client_mock.list_agents = AsyncMock(
            side_effect=CloudTalkAuthError(401, "bad creds")
        )
        enter_mock.return_value = client_mock
        resp = await app_client.get(
            "/api/cloudtalk/agents", headers=app_auth_headers
        )

    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_agents_generic_error_still_502(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Non-auth CloudTalk failures stay as 502 (gateway error)."""
    monkeypatch.setattr("app.core.config.settings.CLOUDTALK_ENABLED", True)
    monkeypatch.setattr(
        "app.core.config.settings.CLOUDTALK_API_KEY_ID", "fake-id"
    )
    monkeypatch.setattr(
        "app.core.config.settings.CLOUDTALK_API_KEY_SECRET", "fake-secret"
    )

    with patch(
        "app.api.cloudtalk.CloudTalkClient.__aenter__",
        new_callable=AsyncMock,
    ) as enter_mock:
        client_mock = AsyncMock()
        client_mock.list_agents = AsyncMock(
            side_effect=CloudTalkError(500, "upstream boom")
        )
        enter_mock.return_value = client_mock
        resp = await app_client.get(
            "/api/cloudtalk/agents", headers=app_auth_headers
        )

    assert resp.status_code == 502
