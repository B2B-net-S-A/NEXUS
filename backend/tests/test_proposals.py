"""Integration + unit tests for AI candidate proposal snapshots (Phase 13).

Covers:
- POST /api/jobs triggers a proposal snapshot
- GET /api/jobs/{id}/proposals/latest returns the latest row
- GET /api/jobs/{id}/proposals lists history (paginated)
- POST /api/jobs/{id}/proposals/regenerate creates a new pending snapshot
- compute_proposal_for_job handles Qdrant/Voyage outages without raising
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.proposal_snapshot import (
    ProposalSnapshot,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_READY,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def proposals_client() -> AsyncClient:
    """In-process client with rate limits disabled and app exceptions swallowed."""
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _create_job(client: AsyncClient, headers: dict) -> int:
    """Create a job via the public API and return its id.

    Seeds a throwaway client first (migration 0120: NOT NULL on client_id).
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"ProposalsClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        cli_id = cli.id

    payload = {
        "title": f"Proposals Pytest Job {uuid.uuid4().hex[:6]}",
        "description": "Backend engineer with Python + FastAPI",
        # `level` to enum stringowy (junior/mid/senior/expert), nie liczba —
        # `JobCreate` waliduje go wprost. „mid" jest uczciwym odczytem
        # `years: 3`; sama wartość nie wpływa na asercje tych testów.
        "must_skills": [{"name": "Python", "level": "mid", "years": 3}],
        "client_id": cli_id,
    }
    resp = await client.post("/api/jobs", headers=headers, json=payload)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def _regenerate(client: AsyncClient, headers: dict, job_id: int) -> None:
    """Wymuś powstanie snapshotu propozycji.

    Snapshot NIE powstaje przy tworzeniu rekrutacji — to decyzja projektowa,
    nie brak: ranking liczy się dopiero przy przekazaniu do searchu, żeby nie
    powstawał „przed Championem" (patrz docstring `job_readiness.py`). Poza
    handoffem jedyną drogą jest ręczna regeneracja, i tej używamy tutaj.
    """
    resp = await client.post(
        f"/api/jobs/{job_id}/proposals/regenerate", headers=headers
    )
    assert resp.status_code == 202, resp.text


# ── Integration tests ──────────────────────────────────────────────────────


async def test_create_job_does_not_rank_before_handoff(
    proposals_client: AsyncClient, app_auth_headers: dict
):
    """Samo utworzenie rekrutacji NIE liczy rankingu — i tak ma zostać.

    Ten test do 09.2026 twierdził coś odwrotnego („Every POST /api/jobs should
    schedule a proposal snapshot") i nie przeszedł ANI RAZU: commit, który go
    dodał (`86e52411`), w ogóle nie dotykał `app/api/jobs.py`. Opisywał
    intencję, której nigdy nie wdrożono.

    Dzisiejszy projekt świadomie jej przeczy. `create_pending_snapshot` woła
    się w DWÓCH miejscach — przy przekazaniu do searchu i przy ręcznej
    regeneracji — bo ranking policzony przed wypełnieniem Profilu Championa
    powstałby z samej treści ogłoszenia i byłby słaby. Dokładnie temu ma
    zapobiegać bramka handoffu (patrz `app/services/job_readiness.py`).

    Odwrócenie asercji zamiast skasowania testu jest celowe: granica, która
    nie ma strażnika, wraca przy pierwszym „to chyba powinno się liczyć od
    razu".
    """
    job_id = await _create_job(proposals_client, app_auth_headers)

    async with AsyncSessionLocal() as db:
        snap = await db.scalar(
            select(ProposalSnapshot).where(ProposalSnapshot.job_id == job_id)
        )
    assert snap is None, (
        "utworzenie rekrutacji policzyło ranking — to omija bramkę handoffu, "
        "która istnieje po to, żeby ranking nie powstawał przed Championem"
    )


async def test_get_latest_proposal_returns_snapshot(
    proposals_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _create_job(proposals_client, app_auth_headers)
    await _regenerate(proposals_client, app_auth_headers, job_id)
    resp = await proposals_client.get(
        f"/api/jobs/{job_id}/proposals/latest", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["status"] in (STATUS_PENDING, STATUS_READY, STATUS_FAILED)
    assert "candidates" in body
    assert isinstance(body["candidates"], list)


async def test_get_latest_proposal_returns_404_for_job_without_snapshots(
    proposals_client: AsyncClient, app_auth_headers: dict
):
    """Legacy jobs created before Phase 13 don't have a snapshot."""
    # Insert a bare Job without firing the create_job pipeline.
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"ProposalsLegacy-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Legacy {uuid.uuid4().hex[:6]}",
            status=JobStatus.draft,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id

    resp = await proposals_client.get(
        f"/api/jobs/{job_id}/proposals/latest", headers=app_auth_headers
    )
    assert resp.status_code == 404


async def test_regenerate_creates_new_pending_snapshot(
    proposals_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _create_job(proposals_client, app_auth_headers)

    # Count existing snapshots for this job first.
    async with AsyncSessionLocal() as db:
        before = (
            await db.execute(
                select(ProposalSnapshot).where(ProposalSnapshot.job_id == job_id)
            )
        ).all()

    resp = await proposals_client.post(
        f"/api/jobs/{job_id}/proposals/regenerate",
        headers=app_auth_headers,
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["source"] == "manual_regenerate"

    async with AsyncSessionLocal() as db:
        after = (
            await db.execute(
                select(ProposalSnapshot).where(ProposalSnapshot.job_id == job_id)
            )
        ).all()
    assert len(after) == len(before) + 1


async def test_list_proposals_paginates(
    proposals_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _create_job(proposals_client, app_auth_headers)
    await _regenerate(proposals_client, app_auth_headers, job_id)
    resp = await proposals_client.get(
        f"/api/jobs/{job_id}/proposals?page=1&page_size=5",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["page"] == 1
    assert body["page_size"] == 5
    assert body["total"] >= 1
    assert isinstance(body["items"], list)


async def test_regenerate_requires_tac_plus_role(
    proposals_client: AsyncClient, app_auth_headers: dict
):
    """Regenerate is behind TacPlus guard — admin (our test user) should pass."""
    job_id = await _create_job(proposals_client, app_auth_headers)
    resp = await proposals_client.post(
        f"/api/jobs/{job_id}/proposals/regenerate",
        headers=app_auth_headers,
    )
    assert resp.status_code == 202


# ── Unit test for the task itself ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_compute_proposal_handles_empty_pool_gracefully(
    proposals_client: AsyncClient, app_auth_headers: dict
):
    """
    If Qdrant returns no hits and DB has no candidates, the task must mark
    the snapshot ready with zero candidates — not failed.
    """
    from app.tasks.compute_proposals import (
        compute_proposal_for_job,
        create_pending_snapshot,
    )

    job_id = await _create_job(proposals_client, app_auth_headers)

    snapshot_id = await create_pending_snapshot(job_id, source="manual_regenerate")

    with (
        patch(
            "app.services.embedding_service.search_candidates_semantic",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.services.embedding_service.embed_job",
            new=AsyncMock(return_value=True),
        ),
    ):
        await compute_proposal_for_job(snapshot_id, job_id, top_k=10)

    async with AsyncSessionLocal() as db:
        snap = await db.scalar(
            select(ProposalSnapshot).where(ProposalSnapshot.id == snapshot_id)
        )
    assert snap is not None
    # With no candidates in the fallback pool, we still finish cleanly.
    assert snap.status in (STATUS_READY, STATUS_FAILED)
    if snap.status == STATUS_READY:
        assert snap.candidate_ids == []
        assert snap.breakdowns == []
