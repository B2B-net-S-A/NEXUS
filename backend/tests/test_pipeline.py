"""Tests for pipeline API — runs against live backend."""
import pytest
from httpx import AsyncClient


async def test_list_stages(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/pipeline/stages", headers=auth_headers)
    assert resp.status_code == 200
    stages = resp.json()
    assert len(stages) >= 10
    stage_names = {s["stage"] for s in stages}
    assert "prep_call" in stage_names
    assert "cv_sent" in stage_names
    assert "client_interview" in stage_names
    assert "acceptance" in stage_names
    categories = {s["category"] for s in stages}
    assert "internal" in categories
    assert "external" in categories
    assert "terminal" in categories


async def test_kanban_view(client: AsyncClient, auth_headers: dict):
    # Get first job
    jobs = await client.get("/api/jobs?page_size=1", headers=auth_headers)
    job_id = jobs.json()["items"][0]["id"]

    resp = await client.get(f"/api/pipeline/kanban/{job_id}", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert len(data["columns"]) >= 10
    for col in data["columns"]:
        assert "stage" in col
        assert "category" in col
        assert col["count"] == len(col["items"])


async def test_kanban_items_have_days(client: AsyncClient, auth_headers: dict):
    jobs = await client.get("/api/jobs?page_size=1", headers=auth_headers)
    job_id = jobs.json()["items"][0]["id"]
    resp = await client.get(f"/api/pipeline/kanban/{job_id}", headers=auth_headers)
    for col in resp.json()["columns"]:
        for item in col["items"]:
            assert "days_in_stage" in item
            assert item["days_in_stage"] >= 0


async def test_pipeline_overview(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/pipeline/overview", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "jobs" in data
    assert "bottlenecks" in data
    assert "aging_alerts" in data
    assert "opportunities" in data
    assert "workload" in data
    assert "stage_labels" in data
    assert len(data["jobs"]) > 0


async def test_overview_has_stage_labels(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/pipeline/overview", headers=auth_headers)
    labels = resp.json()["stage_labels"]
    assert "prep_call" in labels
    assert "acceptance" in labels
    assert labels["prep_call"] == "Preparation Call"


async def test_move_candidate(client: AsyncClient, auth_headers: dict):
    # Get a candidate and job from overview
    overview = await client.get("/api/pipeline/overview", headers=auth_headers)
    job = overview.json()["jobs"][0]
    job_id = job["job_id"]

    # Get kanban to find a candidate
    kanban = await client.get(f"/api/pipeline/kanban/{job_id}", headers=auth_headers)
    candidate_id = None
    for col in kanban.json()["columns"]:
        if col["items"]:
            candidate_id = col["items"][0]["candidate_id"]
            break
    assert candidate_id is not None

    resp = await client.post("/api/pipeline/move", headers=auth_headers, json={
        "candidate_id": candidate_id,
        "job_id": job_id,
        "stage": "screening",
        "notes": "Test move",
        "rating": 4,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["stage"] == "screening"
    assert data["rating"] == 4


async def test_stage_history(client: AsyncClient, auth_headers: dict):
    overview = await client.get("/api/pipeline/overview", headers=auth_headers)
    job = overview.json()["jobs"][0]
    job_id = job["job_id"]
    kanban = await client.get(f"/api/pipeline/kanban/{job_id}", headers=auth_headers)
    candidate_id = None
    for col in kanban.json()["columns"]:
        if col["items"]:
            candidate_id = col["items"][0]["candidate_id"]
            break

    resp = await client.get(f"/api/pipeline/history/{candidate_id}/{job_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_unauthorized_access(client: AsyncClient):
    resp = await client.get("/api/pipeline/stages")
    assert resp.status_code in (401, 403)
    resp = await client.get("/api/pipeline/overview")
    assert resp.status_code in (401, 403)


async def test_bulk_move(client: AsyncClient, auth_headers: dict):
    """POST /api/pipeline/bulk-move moves multiple candidates."""
    overview = await client.get("/api/pipeline/overview", headers=auth_headers)
    job = overview.json()["jobs"][0]
    job_id = job["job_id"]

    kanban = await client.get(f"/api/pipeline/kanban/{job_id}", headers=auth_headers)
    candidate_ids = []
    for col in kanban.json()["columns"]:
        for item in col["items"]:
            candidate_ids.append(item["candidate_id"])
            if len(candidate_ids) >= 2:
                break
        if len(candidate_ids) >= 2:
            break

    if len(candidate_ids) < 2:
        return  # Not enough data

    resp = await client.post("/api/pipeline/bulk-move", headers=auth_headers, json={
        "candidate_ids": candidate_ids,
        "job_id": job_id,
        "stage": "interview",
        "notes": "Bulk move test",
    })
    assert resp.status_code == 200
    assert resp.json()["moved"] == 2
