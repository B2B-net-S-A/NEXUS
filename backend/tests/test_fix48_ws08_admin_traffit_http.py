"""`GET /api/admin/traffit/sync/status` po usunięciu kodu Traffita — przez HTTP.

Wymaga Postgresa (fixture `app_client` zakłada admina w bazie testowej).
"""

from __future__ import annotations

import pytest

MESSAGE = (
    "Traffit jest wyłączony od 14.10.2026 — NEXUS nie importuje już danych z Traffita."
)


@pytest.mark.asyncio
async def test_status_stays_readable_and_says_retired(
    app_client, app_auth_headers
) -> None:
    resp = await app_client.get(
        "/api/admin/traffit/sync/status", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is False
    assert body["retired_on"] == "2026-10-14"
    assert body["retired_message"] == MESSAGE
    assert "states" in body
