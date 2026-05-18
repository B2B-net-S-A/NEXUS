"""Tests for DynaReporter B.1 Profile endpoint.

Pierwszy moduł migracji — walidacja wzorca end-to-end:
- GET /api/dynareporter/profile/me wymaga JWT (401 bez auth)
- Z auth headers zwraca {user_id, email, full_name, role,
  allowed_sections, dynareporter_legacy_id}
- allowed_sections + dynareporter_legacy_id muszą istnieć (z 0111 migration)
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_profile_requires_auth(app_client: AsyncClient) -> None:
    """Bez auth headers → 403 lub 401 (HTTPBearer default)."""
    response = await app_client.get("/api/dynareporter/profile/me")
    assert response.status_code in (401, 403), (
        f"Expected 401/403 without auth, got {response.status_code}"
    )


@pytest.mark.asyncio
async def test_profile_returns_user_info(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Z prawidłowym JWT → 200 + standard profile response shape."""
    response = await app_client.get(
        "/api/dynareporter/profile/me", headers=app_auth_headers
    )
    assert response.status_code == 200, (
        f"Expected 200 with auth, got {response.status_code}: {response.text}"
    )
    body = response.json()
    # Core identity fields
    assert isinstance(body["user_id"], int)
    assert "@" in body["email"]
    assert isinstance(body["full_name"], str) and body["full_name"]
    assert body["role"] in (
        "admin", "head_of_recruitment", "delivery_lead",
        "tac", "recruiter", "sourcer", "user",
    )
    # B.0 migration 0111 columns
    assert isinstance(body["allowed_sections"], list)
    # Test admin nie ma jeszcze sections (pre-ETL), więc lista pusta dopuszczalna
    for section in body["allowed_sections"]:
        assert section in (
            "body-leasing", "sales", "delivery-lead", "placements",
            "clients-mrr", "competitions", "przetargi", "board",
            "sales-mgmt", "mindy", "admin",
        ), f"Unknown section: {section}"
    # dynareporter_legacy_id — None dla nexus-only userów (przed ETL)
    assert body["dynareporter_legacy_id"] is None or isinstance(
        body["dynareporter_legacy_id"], int
    )
