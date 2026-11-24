"""Górne granice ``limit`` na listach (audyt r5, 24.11.2026).

Bez ``le=`` jedno żądanie ``?limit=1000000`` zrzucało całą tabelę
(``Activity`` na pulpicie, kursy walut) w jednej odpowiedzi.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize(
    ("limit", "status"),
    [(101, 422), (0, 422), (100, 200), (1, 200)],
)
async def test_recent_activity_limit_is_bounded(
    app_client: AsyncClient, app_auth_headers: dict[str, str], limit: int, status: int
) -> None:
    resp = await app_client.get(
        "/api/dashboard/recent-activity",
        params={"limit": limit},
        headers=app_auth_headers,
    )
    assert resp.status_code == status, resp.text
    if status == 200:
        assert len(resp.json()) <= limit


@pytest.mark.parametrize(
    ("limit", "status"),
    [(501, 422), (0, 422), (500, 200)],
)
async def test_fx_rates_limit_is_bounded(
    app_client: AsyncClient, app_auth_headers: dict[str, str], limit: int, status: int
) -> None:
    resp = await app_client.get(
        "/api/fx", params={"limit": limit}, headers=app_auth_headers
    )
    assert resp.status_code == status, resp.text
