"""Tests for jobs API."""

from httpx import AsyncClient


async def test_list_jobs(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/jobs", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert data["total"] > 0


async def test_jobs_have_candidate_count(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/jobs", headers=auth_headers)
    items = resp.json()["items"]
    for job in items:
        assert "candidate_count" in job
        assert isinstance(job["candidate_count"], int)


async def test_get_job(client: AsyncClient, auth_headers: dict):
    listing = await client.get("/api/jobs?page_size=1", headers=auth_headers)
    jid = listing.json()["items"][0]["id"]
    resp = await client.get(f"/api/jobs/{jid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == jid


async def test_job_not_found(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/jobs/99999", headers=auth_headers)
    assert resp.status_code == 404


async def test_jobs_unauthorized(client: AsyncClient):
    resp = await client.get("/api/jobs")
    assert resp.status_code in (401, 403)
