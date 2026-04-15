"""Tests for contracts API."""
from httpx import AsyncClient


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
