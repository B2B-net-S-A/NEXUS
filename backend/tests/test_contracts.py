"""Tests for contracts API."""
from httpx import AsyncClient


# Legacy live-server smoke tests (skipped unless RUN_LIVE_TESTS=1)

async def test_list_contracts(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/contracts", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


async def test_contracts_have_margin(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/contracts", headers=auth_headers)
    for c in resp.json()["items"]:
        if c.get("rate_client") and c.get("rate_candidate"):
            assert "margin" in c


async def test_expiring_contracts(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/contracts/expiring", headers=auth_headers)
    assert resp.status_code == 200


async def test_contracts_unauthorized(client: AsyncClient):
    resp = await client.get("/api/contracts")
    assert resp.status_code in (401, 403)


# In-process tests (run always, no rate-limit issues)

async def test_get_contract_detail_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get("/api/contracts/999999", headers=app_auth_headers)
    assert resp.status_code == 404


async def test_contract_activities_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contracts/999999/activities", headers=app_auth_headers
    )
    assert resp.status_code == 404


async def test_contract_rate_history_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contracts/999999/rate-history", headers=app_auth_headers
    )
    assert resp.status_code == 404


async def test_contract_detail_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    """If any contracts exist, GET detail must include denormalized names."""
    list_resp = await app_client.get("/api/contracts", headers=app_auth_headers)
    items = list_resp.json().get("items", [])
    if not items:
        return
    cid = items[0]["id"]
    detail = await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
    assert detail.status_code == 200
    body = detail.json()
    assert "candidate_name" in body
    assert "client_name" in body
    assert "job_title" in body


async def test_contract_activities_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    list_resp = await app_client.get("/api/contracts", headers=app_auth_headers)
    items = list_resp.json().get("items", [])
    if not items:
        return
    cid = items[0]["id"]
    resp = await app_client.get(
        f"/api/contracts/{cid}/activities", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_contract_rate_history_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    list_resp = await app_client.get("/api/contracts", headers=app_auth_headers)
    items = list_resp.json().get("items", [])
    if not items:
        return
    cid = items[0]["id"]
    resp = await app_client.get(
        f"/api/contracts/{cid}/rate-history", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
