"""Tests for AI-recommended searches on the Champion Profile.

Covers: generation (mocked central AI gateway) with whitelist validation, the DL
decision flow (approve → materialised pinned+shared SavedSearch; reject;
reset → SavedSearch deleted), PUT preservation, and the phase4 list change
that surfaces other users' shared searches pinned to a job.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


SAMPLE_SEARCHES_OUTPUT = {
    "searches": [
        {
            "name": "Precyzyjna: Java + Kafka",
            "rationale": "Must-have z profilu championa.",
            "params": {
                "skills_must": ["Java", "Kafka"],
                "q_any_groups": [["system bankowy", "bankowość"]],
                "experience_years_min": 5,
            },
        },
        {
            "name": "Szeroka: alternatywy messagingu",
            "rationale": "Kafka zamienna z RabbitMQ wg konsultanta.",
            "params": {
                "skills_must": ["Java"],
                "skills_any": ["Kafka", "RabbitMQ"],
            },
        },
        {
            # Invalid — empty params → must be dropped server-side.
            "name": "Pusta strategia",
            "rationale": "",
            "params": {},
        },
    ]
}


@pytest.fixture
def _patch_ai_gateway(monkeypatch):
    from app.services import champion_draft_service

    async def call(request):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            content=request.structured_validator(SAMPLE_SEARCHES_OUTPUT)
        )

    monkeypatch.setattr(champion_draft_service.ai_gateway, "call", call)


async def _seed_job() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        client = Client(name="RecSearchClient Sp. z o.o.")
        db.add(client)
        await db.flush()
        job = Job(
            title="Senior Java Developer",
            client_id=client.id,
            description="",
            requirements="Java, Kafka, microservices",
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _generate(app_client, app_auth_headers, job_id: int) -> list[dict]:
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/recommended-searches/generate",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["champion_profile"]["recommended_searches"]


@pytest.mark.asyncio
async def test_generate_validates_and_drops_empty(
    app_client, app_auth_headers, _patch_ai_gateway
):
    job_id = await _seed_job()
    searches = await _generate(app_client, app_auth_headers, job_id)
    # 3 raw proposals, the empty-params one dropped.
    assert len(searches) == 2
    assert all(s["status"] == "proposed" for s in searches)
    assert searches[0]["params"]["skills_must"] == ["Java", "Kafka"]
    assert searches[0]["generated_at"]


@pytest.mark.asyncio
async def test_approve_materialises_pinned_shared_saved_search(
    app_client, app_auth_headers, _patch_ai_gateway
):
    job_id = await _seed_job()
    searches = await _generate(app_client, app_auth_headers, job_id)
    sid = searches[0]["id"]

    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/recommended-searches/decision",
        json={"search_id": sid, "action": "approve"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    entry = next(
        s
        for s in resp.json()["champion_profile"]["recommended_searches"]
        if s["id"] == sid
    )
    assert entry["status"] == "approved"
    assert entry["saved_search_id"]
    assert entry["decided_by_name"]

    # The materialised SavedSearch is pinned to the job + shared, and its
    # filters are a CandidateSearchRequest-shaped dump.
    listing = await app_client.get(
        f"/api/saved-searches?entity=candidates&pinned_to_job_id={job_id}",
        headers=app_auth_headers,
    )
    assert listing.status_code == 200
    rows = [r for r in listing.json() if r["id"] == entry["saved_search_id"]]
    assert rows, "approved search not visible in pinned listing"
    assert rows[0]["shared"] is True
    assert rows[0]["pinned_to_job_id"] == job_id
    assert rows[0]["filters"]["skills_must"] == ["Java", "Kafka"]


@pytest.mark.asyncio
async def test_reject_and_reset_roundtrip(
    app_client, app_auth_headers, _patch_ai_gateway
):
    job_id = await _seed_job()
    searches = await _generate(app_client, app_auth_headers, job_id)
    sid = searches[0]["id"]

    reject = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/recommended-searches/decision",
        json={"search_id": sid, "action": "reject"},
        headers=app_auth_headers,
    )
    entry = next(
        s
        for s in reject.json()["champion_profile"]["recommended_searches"]
        if s["id"] == sid
    )
    assert entry["status"] == "rejected"

    reset = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/recommended-searches/decision",
        json={"search_id": sid, "action": "reset"},
        headers=app_auth_headers,
    )
    entry = next(
        s
        for s in reset.json()["champion_profile"]["recommended_searches"]
        if s["id"] == sid
    )
    assert entry["status"] == "proposed"
    assert entry["decided_by_id"] is None


@pytest.mark.asyncio
async def test_reset_after_approve_deletes_saved_search(
    app_client, app_auth_headers, _patch_ai_gateway
):
    job_id = await _seed_job()
    searches = await _generate(app_client, app_auth_headers, job_id)
    sid = searches[0]["id"]

    approve = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/recommended-searches/decision",
        json={"search_id": sid, "action": "approve"},
        headers=app_auth_headers,
    )
    saved_id = next(
        s
        for s in approve.json()["champion_profile"]["recommended_searches"]
        if s["id"] == sid
    )["saved_search_id"]

    await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/recommended-searches/decision",
        json={"search_id": sid, "action": "reset"},
        headers=app_auth_headers,
    )
    listing = await app_client.get(
        f"/api/saved-searches?entity=candidates&pinned_to_job_id={job_id}",
        headers=app_auth_headers,
    )
    assert all(r["id"] != saved_id for r in listing.json())


@pytest.mark.asyncio
async def test_put_profile_preserves_recommended_searches(
    app_client, app_auth_headers, _patch_ai_gateway
):
    job_id = await _seed_job()
    searches = await _generate(app_client, app_auth_headers, job_id)
    assert len(searches) == 2

    put = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        json={
            "sourcing": {
                "sources": ["linkedin"],
                "keywords": "java",
                "target_companies": "",
                "notes": "",
            },
            "recommended_searches": [],  # próba wyczyszczenia
        },
        headers=app_auth_headers,
    )
    assert put.status_code == 200
    assert len(put.json()["champion_profile"]["recommended_searches"]) == 2


@pytest.mark.asyncio
async def test_decision_404_for_unknown_search(app_client, app_auth_headers):
    job_id = await _seed_job()
    resp = await app_client.post(
        f"/api/jobs/{job_id}/champion-profile/recommended-searches/decision",
        json={"search_id": "nope", "action": "approve"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 404
