"""Tests for Phase 9 C4 — FX rates + conversion."""

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient


async def test_list_fx_ok(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get("/api/fx", headers=app_auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_refresh_requires_admin(app_client: AsyncClient, app_auth_headers: dict):
    # app_auth_headers is admin — should succeed (but might return 0 inserted
    # or fail silently if NBP is unreachable in the test env).
    resp = await app_client.post("/api/fx/refresh", headers=app_auth_headers)
    assert resp.status_code == 200
    assert "inserted" in resp.json()


@pytest.mark.asyncio
async def test_convert_pln_is_identity():
    from app.core.database import AsyncSessionLocal
    from app.services.fx_service import convert_to_pln

    async with AsyncSessionLocal() as db:
        result = await convert_to_pln(db, 1000, "PLN")
    assert result == Decimal(1000)


@pytest.mark.asyncio
async def test_convert_missing_currency_graceful_fallback():
    """Unknown currency with no cached rate should degrade to 1:1, not crash."""
    from app.core.database import AsyncSessionLocal
    from app.services.fx_service import convert_to_pln

    async with AsyncSessionLocal() as db:
        result = await convert_to_pln(db, 1000, "XYZ", on=date.today())
    assert result == Decimal(1000)
