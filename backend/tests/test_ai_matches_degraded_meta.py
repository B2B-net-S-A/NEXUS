"""Awaria wyszukiwania semantycznego na `/ai-matches` musi być OZNACZONA.

Strona rekrutacji ma gotowy baner „wyszukiwanie semantyczne jest chwilowo
niedostępne" wpięty w `data.meta.degraded` — a ten endpoint nigdy żadnego
`meta` nie zwracał. Padnięty Qdrant/Voyage renderował się więc albo jako
zwyczajna, nieoznaczona lista dopasowań (rekruter dodaje z niej ludzi do
pipeline'u i wysyła CV do klienta), albo jako „Brak pasujących kandydatów
w bazie" — czyli awaria udająca pustkę.

Regresja jest CICHA: odpowiedź nadal ma 200 i sensownie wyglądające procenty.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.job import Job


@pytest_asyncio.fixture
async def degraded_fixture():
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"AIMatch Meta Client {unique}")
        db.add(client)
        await db.flush()

        job = Job(
            title=f"AIMatch Meta Job {unique}",
            client_id=client.id,
            description="Python backend engineer",
            requirements="python, fastapi",
            hiring_manager_contact_id=None,
        )
        cand = Candidate(
            name="Meta",
            lastname=f"Kandydat{unique}",
            email=f"meta-{unique}@example.com",
            status=CandidateStatus.active,
            skills=[{"name": "python"}, {"name": "fastapi"}],
        )
        db.add_all([job, cand])
        await db.commit()
        ids = (job.id, cand.id, client.id)

    yield ids

    job_id, cand_id, client_id = ids
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id == cand_id))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


def _widen_pool(monkeypatch) -> None:
    """Fallback bierze `LIMIT effective_pool` BEZ `ORDER BY` — patrz siostrzany
    test bramki dopuszczalności."""
    monkeypatch.setattr(settings, "MATCH_POOL_SIZE", 100_000)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_provider_outage_is_flagged_as_degraded(
    app_client: AsyncClient, app_auth_headers: dict, degraded_fixture, monkeypatch
):
    """Padnięty provider: `degraded=true` i powód odróżniający go od pustki."""
    job_id, _cand_id, _client_id = degraded_fixture
    _widen_pool(monkeypatch)

    from app.services.embedding_service import SemanticSearchUnavailable

    async def _outage(*_a, **_kw):
        raise SemanticSearchUnavailable("qdrant down")

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", _outage
    )

    resp = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 0.0, "limit": 50},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["search_type"] == "tag_fallback"
    assert body["meta"]["degraded"] is True, (
        "awaria providera wróciła jako zwyczajna lista dopasowań — strona "
        "rekrutacji nie ma z czego wyrenderować banera"
    )
    assert body["meta"]["reason"] == "semantic_unavailable"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_healthy_but_empty_retrieval_is_also_degraded_with_its_own_reason(
    app_client: AsyncClient, app_auth_headers: dict, degraded_fixture, monkeypatch
):
    """Zdrowy Qdrant z zerem trafień też schodzi do rankingu po tagach.

    To nie jest ranking semantyczny, więc `degraded` zostaje — ale `reason`
    musi odróżniać chudy indeks od awarii, inaczej diagnoza „czemu lista jest
    dziwna" jest zgadywaniem.
    """
    job_id, _cand_id, _client_id = degraded_fixture
    _widen_pool(monkeypatch)

    async def _no_hits(*_a, **_kw):
        return []

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", _no_hits
    )

    resp = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 0.0, "limit": 50},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["meta"]["degraded"] is True
    assert body["meta"]["reason"] == "no_semantic_hits"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_healthy_semantic_ranking_is_not_flagged(
    app_client: AsyncClient, app_auth_headers: dict, degraded_fixture, monkeypatch
):
    """Zdrowa ścieżka NIE może krzyczeć — baner na każdej liście przestaje znaczyć."""
    job_id, cand_id, _client_id = degraded_fixture

    from unittest.mock import AsyncMock
    from app.services.full_search_measurement import VectorMeasurement

    monkeypatch.setattr(
        "app.services.canonical_fit.request_vector", AsyncMock(return_value=[1, 0])
    )

    async def measured(_vector, candidates):
        return {c.id: VectorMeasurement(0.91, "measured") for c in candidates}

    monkeypatch.setattr("app.services.canonical_fit.measure_candidates", measured)

    async def _one_hit(*_a, **_kw):
        return [{"candidate_id": cand_id, "score": 0.91}]

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic", _one_hit
    )

    resp = await app_client.get(
        f"/api/jobs/{job_id}/ai-matches",
        params={"min_score": 0.0, "limit": 50},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["search_type"].startswith("semantic")
    assert body["meta"]["degraded"] is False
    assert body["meta"]["reason"] is None
