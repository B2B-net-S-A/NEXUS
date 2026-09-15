"""Pipeline API smoke tests — in-process client, own seeded data.

Ported from the live-server suite (it relied on a running backend and on
"the first job in the database" having candidates). Every test now seeds a
unique client/job/candidate and talks to the app in-process, so it runs in CI.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal

MOVE = "/api/pipeline/move"


async def _seed_job() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"PipeSmoke {tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"PipeSmoke job {tag}",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Pipe", lastname=f"Smoke-{tag}", email=f"pipe-{tag}@example.com"
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _move(app_client, headers, candidate_id, job_id, stage, **extra) -> dict:
    resp = await app_client.post(
        MOVE,
        headers=headers,
        json={"candidate_id": candidate_id, "job_id": job_id, "stage": stage, **extra},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_list_stages(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get("/api/pipeline/stages", headers=app_auth_headers)
    assert resp.status_code == 200
    stages = resp.json()
    assert len(stages) >= 10
    stage_names = {s["stage"] for s in stages}
    assert {"prep_call", "cv_sent", "client_interview", "acceptance"} <= stage_names
    categories = {s["category"] for s in stages}
    assert {"internal", "external", "terminal"} <= categories


async def test_kanban_view(app_client: AsyncClient, app_auth_headers: dict):
    job_id, cand_id = await _seed_job(), await _seed_candidate()
    await _move(app_client, app_auth_headers, cand_id, job_id, "screening")

    resp = await app_client.get(
        f"/api/pipeline/kanban/{job_id}", headers=app_auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["job_id"] == job_id
    assert data["columns"]
    seen = set()
    for col in data["columns"]:
        assert "stage" in col
        assert "category" in col
        assert col["count"] == len(col["items"])
        for item in col["items"]:
            assert item["days_in_stage"] >= 0
            seen.add(item["candidate_id"])
    assert cand_id in seen


async def test_pipeline_overview(app_client: AsyncClient, app_auth_headers: dict):
    job_id, cand_id = await _seed_job(), await _seed_candidate()
    await _move(app_client, app_auth_headers, cand_id, job_id, "screening")

    resp = await app_client.get("/api/pipeline/overview", headers=app_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    for key in ("jobs", "bottlenecks", "aging_alerts", "opportunities", "workload"):
        assert key in data
    assert len(data["jobs"]) > 0
    labels = data["stage_labels"]
    assert labels["prep_call"] == "Preparation Call"
    assert "acceptance" in labels


async def test_move_candidate_and_stage_history(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id, cand_id = await _seed_job(), await _seed_candidate()

    data = await _move(
        app_client,
        app_auth_headers,
        cand_id,
        job_id,
        "screening",
        notes="Test move",
        rating=4,
    )
    assert data["stage"] == "screening"
    assert data["rating"] == 4

    resp = await app_client.get(
        f"/api/pipeline/history/{cand_id}/{job_id}", headers=app_auth_headers
    )
    assert resp.status_code == 200
    history = resp.json()
    assert len(history) >= 1
    assert history[-1]["stage"] == "screening"


async def test_unauthorized_access(app_client: AsyncClient):
    resp = await app_client.get("/api/pipeline/stages")
    assert resp.status_code == 401
    resp = await app_client.get("/api/pipeline/overview")
    assert resp.status_code == 401


async def test_bulk_move(app_client: AsyncClient, app_auth_headers: dict):
    """POST /api/pipeline/bulk-move moves multiple candidates."""
    job_id = await _seed_job()
    cand_ids = [await _seed_candidate(), await _seed_candidate()]
    for cid in cand_ids:
        await _move(app_client, app_auth_headers, cid, job_id, "screening")

    resp = await app_client.post(
        "/api/pipeline/bulk-move",
        headers=app_auth_headers,
        json={
            "candidate_ids": cand_ids,
            "job_id": job_id,
            "stage": "interview",
            "notes": "Bulk move test",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["moved"] == 2
