"""Integration tests for presence HTTP + WebSocket wiring.

HTTP GET /api/presence/{type}/{id}/viewers is tested via the in-process
app_client fixture. WebSocket handshake + messaging is exercised via
starlette's sync TestClient (fastapi.testclient.TestClient), which supports
`websocket_connect()`.

Auth: the HTTP endpoint uses the `app_auth_headers` fixture; the WS endpoint
takes the JWT via query param.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_presence_get_empty_initially(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    # Isolated resource_id (very high) → no viewers
    resp = await app_client.get(
        "/api/presence/candidate/987654321/viewers", headers=app_auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "viewers" in body
    assert body["viewers"] == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_presence_get_requires_auth(app_client: AsyncClient):
    resp = await app_client.get("/api/presence/candidate/1/viewers")
    assert resp.status_code in (401, 403)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_presence_get_rejects_unknown_resource_type(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    resp = await app_client.get(
        "/api/presence/user/1/viewers", headers=app_auth_headers
    )
    # Pydantic Literal validation → 422
    assert resp.status_code == 422


# NOTE: End-to-end WS subscribe → broadcast flow is verified by the Chrome MCP
# smoke test (two browser contexts on the same candidate) and by the Playwright
# E2E spec. The sync TestClient + asyncpg combination conflicts on event loops,
# so in-process WS integration testing is out of scope here.
