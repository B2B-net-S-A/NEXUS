"""Tests for candidates API."""
from httpx import AsyncClient


async def test_list_candidates(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/candidates", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] > 0


async def test_get_candidate(client: AsyncClient, auth_headers: dict):
    listing = await client.get("/api/candidates?page_size=1", headers=auth_headers)
    cid = listing.json()["items"][0]["id"]
    resp = await client.get(f"/api/candidates/{cid}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == cid
    assert "name" in data
    assert "lastname" in data
    assert "email" in data


async def test_candidate_not_found(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/candidates/99999", headers=auth_headers)
    assert resp.status_code == 404


async def test_search_candidates(client: AsyncClient, auth_headers: dict):
    listing = await client.get("/api/candidates?page_size=1", headers=auth_headers)
    name = listing.json()["items"][0]["name"]
    resp = await client.get(f"/api/candidates?q={name}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["total"] >= 1


async def test_candidates_unauthorized(client: AsyncClient):
    resp = await client.get("/api/candidates")
    assert resp.status_code in (401, 403)
