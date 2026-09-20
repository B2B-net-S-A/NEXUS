"""``GET /api/calls/cloudtalk-status`` — the flag the call button hides behind.

CloudTalk is switched off (decision 28.07.2026), yet the profile and quick view
rendered a "Zadzwoń" button whose click always ended in 503. The front now asks
this endpoint first (fail closed). It exposes the kill switch only — never the
API keys or webhook secret.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import settings

URL = "/api/calls/cloudtalk-status"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_status_mirrors_the_kill_switch(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, enabled: bool
):
    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", enabled)
    resp = await app_client.get(URL, headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"enabled": enabled}


@pytest.mark.asyncio
async def test_status_requires_a_logged_in_user(app_client: AsyncClient):
    resp = await app_client.get(URL)
    assert resp.status_code == 401, resp.text
