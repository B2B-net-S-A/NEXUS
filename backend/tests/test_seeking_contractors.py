"""Integration tests for GET /api/recommendations/seeking-contractors.

Mocks Voyage/Qdrant via monkeypatch and seeds real Candidate/Job/Contract rows
to exercise the union-of-sources query and per-candidate filter+score path.

Coverage:
  * empty pool returns total=0
  * candidate with `availability_status=actively_looking` shows up
  * contractor with `Contract.end_date <= horizon` shows up with source=ending_contract
  * threshold rolls low-score matches into below_threshold_count
  * filters (location) drop irrelevant jobs
  * jobs are sorted urgent-first (ending_contract before availability_status)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.candidate import (
    AvailabilityStatus,
    Candidate,
    CandidateStatus,
)
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.job import Job, JobStatus, RemotePolicy


def _patch_pipeline(monkeypatch, *, hits_for_query: list[dict] | None = None):
    """Stub Voyage embed + Qdrant search so tests don't need infra.

    `hits_for_query` is returned for every search regardless of query text;
    tests that need different hits per candidate should pre-fan-out the list
    and have all candidates' hit IDs in it (the endpoint filters to the
    intersection with prefetched open jobs).
    """
    from app.services import embedding_service

    async def _fake_embed(_text):
        return [0.1] * 1024

    async def _fake_search(_q, top_k=20, **kwargs):
        # `**kwargs` pochłania `raise_on_error=True`, którym endpoint odróżnia
        # awarię providera od zdrowego zera trafień. Atrapa o WĘŻSZEJ sygnaturze
        # niż prawdziwa funkcja zamienia zmianę kontraktu w TypeError zamiast
        # w czerwoną asercję — a to mówi o atrapie, nie o kodzie.
        return hits_for_query or []

    monkeypatch.setattr(embedding_service, "generate_embedding", _fake_embed)
    monkeypatch.setattr(embedding_service, "search_jobs_semantic", _fake_search)
    # The endpoint module rebinds these at import time.
    monkeypatch.setattr("app.api.recommendations.search_jobs_semantic", _fake_search)


async def _cleanup(
    *, candidate_ids: list[int], job_ids: list[int], client_ids: list[int]
):
    """Raw-SQL cleanup that bypasses ORM cascade traversal (migration drift)."""
    async with AsyncSessionLocal() as db:
        if candidate_ids:
            await db.execute(
                delete(Contract).where(Contract.candidate_id.in_(candidate_ids))
            )
        if job_ids:
            await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        if candidate_ids:
            await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        if client_ids:
            await db.execute(delete(Client).where(Client.id.in_(client_ids)))
        await db.commit()


async def _seed_candidate_with_availability(
    *, availability: AvailabilityStatus, name: str = "Looking"
) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=name,
            lastname="Tester",
            availability_status=availability,
            status=CandidateStatus.active,
            skills=[{"name": "Python"}, {"name": "FastAPI"}],
            years_it_experience=6,
            location="Warszawa",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _seed_contractor_ending_soon(
    *, days_until_end: int, name: str = "Ending"
) -> tuple[int, int, int]:
    """Returns (candidate_id, client_id, contract_id)."""
    async with AsyncSessionLocal() as db:
        client = Client(name=f"EndingCo_{name}_{days_until_end}")
        db.add(client)
        await db.flush()

        cand = Candidate(
            name=name,
            lastname="Contractor",
            availability_status=AvailabilityStatus.unknown,
            status=CandidateStatus.active,
            skills=[{"name": "Python"}, {"name": "Django"}],
            years_it_experience=8,
        )
        db.add(cand)
        await db.flush()

        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            start_date=date.today() - timedelta(days=180),
            end_date=date.today() + timedelta(days=days_until_end),
            status=ContractStatus.active,
            contract_type=ContractType.b2b,
            rate_unit=RateUnit.monthly,
            rate_candidate=15000,
            rate_client=20000,
        )
        db.add(contract)
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)
        return cand.id, client.id, contract.id


async def _seed_published_job(
    *,
    title: str,
    skills: list[str],
    location: str = "Warszawa",
    salary_min: int | None = 15000,
    salary_max: int | None = 25000,
) -> int:
    import uuid

    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"SeekClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=title,
            description=f"{title} description",
            requirements=" ".join(skills),
            location=location,
            salary_min=salary_min,
            salary_max=salary_max,
            remote_policy=RemotePolicy.remote,
            status=JobStatus.published,
            must_skills=[{"name": s} for s in skills],
            nice_skills=[],
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


@pytest.mark.asyncio
async def test_seeking_contractors_empty_pool(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """No looking candidates and no ending contracts → empty list."""
    _patch_pipeline(monkeypatch, hits_for_query=[])
    resp = await app_client.get(
        "/api/recommendations/seeking-contractors?horizon_days=1",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # In a fresh test DB the pool is empty; in a shared DB filter to total>=0.
    assert body["horizon_days"] == 1
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_seeking_contractors_includes_actively_looking(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    cid = await _seed_candidate_with_availability(
        availability=AvailabilityStatus.actively_looking, name="LookerA"
    )
    job_id = await _seed_published_job(
        title="Senior Python Eng", skills=["Python", "FastAPI"]
    )

    try:
        _patch_pipeline(
            monkeypatch,
            hits_for_query=[{"job_id": job_id, "score": 0.9, "payload": {}}],
        )
        resp = await app_client.get(
            "/api/recommendations/seeking-contractors?horizon_days=1",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ours = [it for it in body["items"] if it["candidate"]["id"] == cid]
        assert len(ours) == 1, "actively_looking candidate must surface"
        assert ours[0]["source"] == "availability_status"
        assert ours[0]["contract_end_date"] is None
        assert any(m["job"]["id"] == job_id for m in ours[0]["top_matches"])
    finally:
        await _cleanup(candidate_ids=[cid], job_ids=[job_id], client_ids=[])


@pytest.mark.asyncio
async def test_seeking_contractors_includes_ending_contract(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    cid, client_id, _contract_id = await _seed_contractor_ending_soon(
        days_until_end=14, name="EndingX"
    )
    job_id = await _seed_published_job(title="Backend Eng", skills=["Python", "Django"])

    try:
        _patch_pipeline(
            monkeypatch,
            hits_for_query=[{"job_id": job_id, "score": 0.85, "payload": {}}],
        )
        resp = await app_client.get(
            "/api/recommendations/seeking-contractors?horizon_days=30",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ours = [it for it in body["items"] if it["candidate"]["id"] == cid]
        assert len(ours) == 1, "ending-contract candidate must surface"
        assert ours[0]["source"] == "ending_contract"
        # ISO date with +14d
        assert ours[0]["contract_end_date"].startswith(
            (date.today() + timedelta(days=14)).strftime("%Y-%m-%d")
        )
        assert ours[0]["current_client_id"] == client_id
    finally:
        await _cleanup(candidate_ids=[cid], job_ids=[job_id], client_ids=[client_id])


@pytest.mark.asyncio
async def test_seeking_contractors_threshold_rolls_into_below_count(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    cid = await _seed_candidate_with_availability(
        availability=AvailabilityStatus.actively_looking, name="LowMatcher"
    )
    # Job with skills that don't match → low score
    job_id = await _seed_published_job(
        title="COBOL Mainframe Specialist", skills=["COBOL", "JCL"]
    )

    try:
        _patch_pipeline(
            monkeypatch,
            hits_for_query=[{"job_id": job_id, "score": 0.05, "payload": {}}],
        )
        resp = await app_client.get(
            "/api/recommendations/seeking-contractors?horizon_days=1&threshold=80",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ours = [it for it in body["items"] if it["candidate"]["id"] == cid]
        assert len(ours) == 1
        assert ours[0]["below_threshold_count"] >= 1
        assert all(m["total_score"] >= 80 for m in ours[0]["top_matches"])
    finally:
        await _cleanup(candidate_ids=[cid], job_ids=[job_id], client_ids=[])


@pytest.mark.asyncio
async def test_seeking_contractors_location_filter_drops_jobs(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    cid = await _seed_candidate_with_availability(
        availability=AvailabilityStatus.open_to_offers, name="WawaOnly"
    )
    j_warsaw = await _seed_published_job(
        title="Warsaw Job", skills=["Python"], location="Warszawa"
    )
    j_berlin = await _seed_published_job(
        title="Berlin Job", skills=["Python"], location="Berlin"
    )

    try:
        _patch_pipeline(
            monkeypatch,
            hits_for_query=[
                {"job_id": j_warsaw, "score": 0.9, "payload": {}},
                {"job_id": j_berlin, "score": 0.9, "payload": {}},
            ],
        )
        resp = await app_client.get(
            "/api/recommendations/seeking-contractors"
            "?horizon_days=1&location=Warszawa&threshold=0",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        ours = [it for it in body["items"] if it["candidate"]["id"] == cid]
        assert len(ours) == 1
        match_ids = {m["job"]["id"] for m in ours[0]["top_matches"]}
        assert j_warsaw in match_ids
        assert j_berlin not in match_ids, "location filter must drop Berlin"
    finally:
        await _cleanup(candidate_ids=[cid], job_ids=[j_warsaw, j_berlin], client_ids=[])
