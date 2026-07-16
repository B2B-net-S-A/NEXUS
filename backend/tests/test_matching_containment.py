"""Containment tests dla modułu matching (audyt M3, 2026-07-16, plan PR A).

Pokrywa:
- M3-API-01: POST /recompute-scores działa (wcześniej route-to-route call
  wysadzał się w runtime na brakującym `request` + sentinelach Query).
- M3-COST-01: legacy /ai-matches waliduje `limit`/`min_score`/`location`
  zanim dotknie jakiegokolwiek providera.
- M3-SEC-01: read-only viewer (rola `user`) nie może czytać powierzchni
  matchingowych z PII ani mutować pipeline przez assign-to-job.
- M3-CACHE-01: degraded scoring (brak similarity z Qdranta) nie zapisuje
  wyników do score cache jako świeżych.
- M3-VEC-01: przy skonfigurowanym Voyage awaria NIE powoduje fallbacku do
  Ollamy (mieszanie przestrzeni wektorowych w jednej kolekcji).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.match_score import CandidateJobMatchScore
from app.models.user import User, UserRole


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def viewer_auth_headers(app_client: AsyncClient) -> dict[str, str]:
    """Read-only viewer (rola `user` — QC/klient) zalogowany hasłem."""
    unique = uuid.uuid4().hex[:8]
    email = f"pytest-viewer-{unique}@example.com"
    password = f"V13wer_{unique}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Pytest Viewer",
                role=UserRole.user,
                is_active=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"viewer login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def seeded_job() -> int:
    """Minimalny klient + job do testów recompute/recommendations."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Matching Containment Client {unique}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Containment Test Job {unique}",
            client_id=client.id,
            description="Python backend engineer, FastAPI, PostgreSQL",
            requirements="python, fastapi, postgresql",
        )
        db.add(job)
        await db.commit()
        return job.id


# ── M3-COST-01: bounds na legacy /ai-matches ────────────────────────────────


@pytest.mark.asyncio
async def test_ai_matches_rejects_huge_limit(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/jobs/1/ai-matches",
        params={"limit": 1_000_000},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_ai_matches_rejects_out_of_range_min_score(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/jobs/1/ai-matches",
        params={"min_score": 5},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.asyncio
async def test_ai_matches_rejects_overlong_location(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/jobs/1/ai-matches",
        params={"location": "x" * 500},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


# ── M3-API-01: recompute-scores znowu działa ────────────────────────────────


@pytest.mark.asyncio
async def test_recompute_scores_returns_200(
    app_client: AsyncClient, app_auth_headers: dict, seeded_job: int
):
    """Przed fixem: TypeError (route-to-route call bez `request`) → 500.

    W CI Qdrant/Voyage są niedostępne, więc core przechodzi ścieżką degraded
    (DB fallback) — endpoint i tak musi zwrócić 200 z podsumowaniem.
    """
    resp = await app_client.post(
        f"/api/jobs/{seeded_job}/recompute-scores",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["job_id"] == seeded_job
    assert body["status"] == "ok"
    assert isinstance(body["evaluated"], int)


# ── M3-SEC-01: viewer bez dostępu do matching PII i mutacji ─────────────────


@pytest.mark.asyncio
async def test_viewer_cannot_read_ai_matches(
    app_client: AsyncClient, viewer_auth_headers: dict
):
    resp = await app_client.get(
        "/api/jobs/1/ai-matches", headers=viewer_auth_headers
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_viewer_cannot_read_recommendations(
    app_client: AsyncClient, viewer_auth_headers: dict
):
    resp = await app_client.get(
        "/api/jobs/1/recommendations", headers=viewer_auth_headers
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_viewer_cannot_assign_candidate_to_job(
    app_client: AsyncClient, viewer_auth_headers: dict
):
    """Mutacja pipeline była dostępna dla read-only viewera (CurrentUser)."""
    resp = await app_client.post(
        "/api/candidates/999999/assign-to-job/999999",
        headers=viewer_auth_headers,
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_operational_user_still_reads_recommendations(
    app_client: AsyncClient, app_auth_headers: dict, seeded_job: int
):
    """Regresja w drugą stronę: admin (rola operacyjna) nadal ma dostęp."""
    resp = await app_client.get(
        f"/api/jobs/{seeded_job}/recommendations", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["job_id"] == seeded_job


# ── M3-CACHE-01: degraded scoring nie zapisuje cache ────────────────────────


@pytest.mark.asyncio
async def test_degraded_scoring_does_not_write_cache(seeded_job: int):
    from app.services.match_score_cache import bulk_get_or_compute

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(name="Cache", lastname=f"Degraded-{unique}")
        db.add(cand)
        await db.commit()
        cand_id = cand.id

    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == seeded_job))
        cand = await db.scalar(select(Candidate).where(Candidate.id == cand_id))

        # Degraded: brak similarity_map (Qdrant down) → wynik jest zwracany,
        # ale NIE persistowany.
        results = await bulk_get_or_compute(
            job, [cand], db, similarity_map=None, allow_cache_write=False
        )
        assert len(results) == 1

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateJobMatchScore).where(
                CandidateJobMatchScore.job_id == seeded_job,
                CandidateJobMatchScore.candidate_id == cand_id,
            )
        )
        assert row is None, "degraded wynik nie może trafić do cache jako fresh"

    # Kontrola: z allow_cache_write=True (default) wpis powstaje.
    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == seeded_job))
        cand = await db.scalar(select(Candidate).where(Candidate.id == cand_id))
        await bulk_get_or_compute(job, [cand], db, similarity_map={cand_id: 0.5})

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateJobMatchScore).where(
                CandidateJobMatchScore.job_id == seeded_job,
                CandidateJobMatchScore.candidate_id == cand_id,
            )
        )
        assert row is not None


# ── M3-VEC-01: brak mieszania przestrzeni Voyage/Ollama ─────────────────────


@pytest.mark.asyncio
async def test_no_ollama_fallback_when_voyage_configured(monkeypatch):
    """Voyage skonfigurowany + awaria → None (degraded), NIGDY wektor Ollamy."""
    from app.core.config import settings
    from app.services import embedding_service as es

    async def _voyage_down(text, *, input_type="document"):
        return None

    async def _ollama_must_not_be_called(text):
        raise AssertionError(
            "Ollama fallback wywołany mimo skonfigurowanego Voyage — "
            "mieszanie przestrzeni wektorowych (M3-VEC-01)"
        )

    monkeypatch.setattr(settings, "VOYAGE_API_KEY", "test-key-present")
    monkeypatch.setattr(es, "_voyage_embed", _voyage_down)
    monkeypatch.setattr(es, "_ollama_embed", _ollama_must_not_be_called)

    # input_type="query" omija cache dokumentów (czysty tor providerów).
    emb = await es.generate_embedding("python developer", input_type="query")
    assert emb is None


@pytest.mark.asyncio
async def test_ollama_fallback_allowed_when_voyage_not_configured(monkeypatch):
    """Tryb offline/dev (brak klucza) — spójna przestrzeń Ollamy jest OK."""
    from app.core.config import settings
    from app.services import embedding_service as es

    async def _ollama_vector(text):
        return [0.1] * es.VECTOR_SIZE

    monkeypatch.setattr(settings, "VOYAGE_API_KEY", "")
    monkeypatch.setattr(es, "_ollama_embed", _ollama_vector)

    emb = await es.generate_embedding("python developer", input_type="query")
    assert emb is not None and len(emb) == es.VECTOR_SIZE
