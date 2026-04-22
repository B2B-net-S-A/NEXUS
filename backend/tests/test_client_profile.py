"""Smoke tests for GET /api/clients/{id}/profile.

Uses the in-process `app_client` fixture so tests run in CI without needing a
live uvicorn. We don't seed full pipeline/contract data — we rely on the
seed.py output that runs in the CI postgres container. Focus: endpoint
response shape + auth + 404 behavior. Deeper unit tests for the aggregation
math should go in a dedicated test_client_profile_math.py once seed data
guarantees enough contracts per client.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def test_profile_requires_auth(app_client: AsyncClient) -> None:
    resp = await app_client.get("/api/clients/1/profile")
    assert resp.status_code in (401, 403)


async def test_profile_404_for_missing_client(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    resp = await app_client.get("/api/clients/99999999/profile", headers=app_auth_headers)
    assert resp.status_code == 404


async def test_profile_returns_expected_shape(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    # Pick any existing client from the list endpoint.
    listing = await app_client.get("/api/clients?page_size=1", headers=app_auth_headers)
    assert listing.status_code == 200
    items = listing.json().get("items") or []
    if not items:
        pytest.skip("No clients seeded — cannot exercise profile shape.")
    client_id = items[0]["id"]

    resp = await app_client.get(f"/api/clients/{client_id}/profile", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Top-level contract
    assert set(body.keys()) >= {"summary", "open_jobs", "active_consultants", "historical"}
    assert isinstance(body["open_jobs"], list)
    assert isinstance(body["active_consultants"], list)
    assert isinstance(body["historical"], dict)
    assert "placements" in body["historical"]
    assert "lost_jobs" in body["historical"]

    # Summary shape
    summary = body["summary"]
    for key in (
        "open_jobs",
        "active_consultants",
        "total_placements",
        "active_mrr",
        "ltv",
    ):
        assert key in summary, f"missing summary.{key}"
        assert isinstance(summary[key], int)
    # avg_time_to_fill_days is Optional[float]
    assert summary.get("avg_time_to_fill_days") is None or isinstance(
        summary["avg_time_to_fill_days"], (int, float)
    )

    # Summary counters must match list lengths (the endpoint doesn't paginate
    # within a single call — it's cheaper than reconciling in UI).
    assert summary["open_jobs"] == len(body["open_jobs"])
    assert summary["active_consultants"] == len(body["active_consultants"])
    assert summary["total_placements"] == summary["active_consultants"] + len(
        body["historical"]["placements"]
    )


async def test_profile_active_consultants_have_candidate_brief(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """If the seed has at least one active contract, verify the candidate payload."""
    listing = await app_client.get("/api/clients?page_size=25", headers=app_auth_headers)
    clients = listing.json().get("items") or []
    for c in clients:
        resp = await app_client.get(
            f"/api/clients/{c['id']}/profile", headers=app_auth_headers
        )
        actives = resp.json().get("active_consultants") or []
        if not actives:
            continue
        row = actives[0]
        assert "contract_id" in row
        assert isinstance(row["candidate"], dict)
        assert "id" in row["candidate"] and "name" in row["candidate"]
        return
    pytest.skip("No active consultants in any client — seed.py did not produce them.")
