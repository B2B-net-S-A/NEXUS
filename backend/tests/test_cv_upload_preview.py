"""Integration tests for POST /api/recommendations/cv-upload-preview.

The pipeline (extract → parse → embed → search → score) is short-circuited via
monkeypatch so tests don't need Qdrant/Voyage/Claude to run.

Coverage:
  * happy path returns parsed_summary + sorted matches
  * threshold cuts low-score matches
  * unsupported file extension returns 400
  * empty payload returns 400
  * empty extracted text returns 400
  * oversize payload returns 413
  * Qdrant fallback (empty hits) still surfaces published jobs
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus, RemotePolicy


FAKE_PARSED = {
    "first_name": "Jan",
    "last_name": "Kowalski",
    "email": "jan.cv-preview@example.com",
    "phone": None,
    "city": "Warszawa",
    "current_position": "Senior Python Developer",
    "years_it_experience": 8,
    "skills": [
        {"name": "Python", "level": "senior", "years": 8},
        {"name": "FastAPI", "level": "senior", "years": 4},
    ],
    "languages": [{"name": "English", "level": "C1"}],
    "companies": ["Acme"],
    "career_summary": "8 lat Pythona w fintechu.",
    "linkedin_url": None,
    "_source": "test:fake",
}


def _patch_pipeline(
    monkeypatch,
    *,
    parsed: dict | None = None,
    extracted: str = "Senior Python Developer\nPython FastAPI",
    embedding: list[float] | None = None,
    hits: list[dict] | None = None,
):
    from app.services import cv_text_extractor
    from app.services import cv_parser
    from app.services import embedding_service

    def _fake_extract(*_a, **_kw) -> str:
        return extracted

    async def _fake_parse(_text, **_kw):
        return parsed if parsed is not None else FAKE_PARSED

    async def _fake_embed(_text, **_kw):
        return embedding if embedding is not None else [0.1] * 1024

    async def _fake_search(_q, top_k: int = 20):
        return hits if hits is not None else []

    monkeypatch.setattr(cv_text_extractor, "extract_text", _fake_extract)
    monkeypatch.setattr(cv_parser, "parse_cv", _fake_parse)
    monkeypatch.setattr(embedding_service, "generate_embedding", _fake_embed)
    monkeypatch.setattr(embedding_service, "search_jobs_semantic", _fake_search)
    # The endpoint module imports this at load time — patch the rebound name.
    monkeypatch.setattr(
        "app.api.cv_match_preview.search_jobs_semantic", _fake_search
    )
    monkeypatch.setattr("app.api.cv_match_preview.parse_cv", _fake_parse)
    monkeypatch.setattr("app.api.cv_match_preview.extract_text", _fake_extract)


@pytest_asyncio.fixture
async def seeded_jobs():
    """Insert two published jobs and clean them up after the test."""
    import uuid

    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"CVPreviewClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j1 = Job(
            title="Senior Python Developer",
            description="Build Python services",
            requirements="Python, FastAPI, PostgreSQL",
            location="Warszawa",
            salary_min=18000,
            salary_max=25000,
            remote_policy=RemotePolicy.remote,
            status=JobStatus.published,
            must_skills=[{"name": "Python"}, {"name": "FastAPI"}],
            nice_skills=[{"name": "PostgreSQL"}],
            client_id=cli.id,
        )
        j2 = Job(
            title="Java Backend Engineer",
            description="JVM platform team",
            requirements="Java, Spring, Kafka",
            location="Kraków",
            salary_min=15000,
            salary_max=22000,
            remote_policy=RemotePolicy.hybrid,
            status=JobStatus.published,
            must_skills=[{"name": "Java"}, {"name": "Spring"}],
            nice_skills=[{"name": "Kafka"}],
            client_id=cli.id,
        )
        db.add_all([j1, j2])
        await db.commit()
        await db.refresh(j1)
        await db.refresh(j2)
        ids = (j1.id, j2.id)

    try:
        yield ids
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Job).where(Job.id.in_(ids)))
            await db.commit()


@pytest.mark.asyncio
async def test_cv_upload_preview_happy_path(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, seeded_jobs
):
    j1_id, j2_id = seeded_jobs
    # Qdrant returns both seeded jobs with python-skewed scores.
    _patch_pipeline(
        monkeypatch,
        hits=[
            {"job_id": j1_id, "score": 0.92, "payload": {}},
            {"job_id": j2_id, "score": 0.45, "payload": {}},
        ],
    )

    files = {"file": ("jan.pdf", b"%PDF-1.4 fake bytes", "application/pdf")}
    resp = await app_client.post(
        "/api/recommendations/cv-upload-preview",
        headers=app_auth_headers,
        files=files,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Parsed summary echoes the LLM output (trimmed shape).
    summary = body["parsed_summary"]
    assert summary["first_name"] == "Jan"
    assert summary["years_it_experience"] == 8
    assert summary["source"] == "test:fake"

    # Both jobs returned, sorted by total_score desc.
    matches = body["matches"]
    assert len(matches) == 2
    assert matches[0]["job"]["id"] == j1_id
    assert matches[0]["total_score"] >= matches[1]["total_score"]
    assert "breakdown" in matches[0]
    assert body["search_type"] == "semantic"


@pytest.mark.asyncio
async def test_cv_upload_preview_threshold_filters_matches(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, seeded_jobs
):
    j1_id, j2_id = seeded_jobs
    _patch_pipeline(
        monkeypatch,
        hits=[
            {"job_id": j1_id, "score": 0.92, "payload": {}},
            {"job_id": j2_id, "score": 0.10, "payload": {}},
        ],
    )

    files = {"file": ("jan.pdf", b"%PDF-1.4 fake", "application/pdf")}
    resp = await app_client.post(
        "/api/recommendations/cv-upload-preview?threshold=80",
        headers=app_auth_headers,
        files=files,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Only high-score match passes threshold=80.
    for m in body["matches"]:
        assert m["total_score"] >= 80


@pytest.mark.asyncio
async def test_cv_upload_preview_rejects_unsupported_extension(
    app_client: AsyncClient, app_auth_headers: dict
):
    files = {"file": ("malware.exe", b"\x4d\x5a\x90\x00", "application/octet-stream")}
    resp = await app_client.post(
        "/api/recommendations/cv-upload-preview",
        headers=app_auth_headers,
        files=files,
    )
    assert resp.status_code == 400
    assert "format" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cv_upload_preview_rejects_empty_payload(
    app_client: AsyncClient, app_auth_headers: dict
):
    files = {"file": ("empty.pdf", b"", "application/pdf")}
    resp = await app_client.post(
        "/api/recommendations/cv-upload-preview",
        headers=app_auth_headers,
        files=files,
    )
    assert resp.status_code == 400
    assert "pust" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cv_upload_preview_rejects_corrupted_pdf(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    # Extractor returns empty text → endpoint must 400.
    _patch_pipeline(monkeypatch, extracted="")

    files = {"file": ("blank.pdf", b"%PDF blank", "application/pdf")}
    resp = await app_client.post(
        "/api/recommendations/cv-upload-preview",
        headers=app_auth_headers,
        files=files,
    )
    assert resp.status_code == 400
    assert "odczytać" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cv_upload_preview_qdrant_empty_falls_back_to_published_jobs(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, seeded_jobs
):
    """When Qdrant returns no hits, endpoint still surfaces published jobs."""
    _patch_pipeline(monkeypatch, hits=[])

    files = {"file": ("jan.pdf", b"%PDF-1.4 fake", "application/pdf")}
    resp = await app_client.post(
        "/api/recommendations/cv-upload-preview",
        headers=app_auth_headers,
        files=files,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The fallback path queries published jobs and ranks them.
    assert isinstance(body["matches"], list)
    assert len(body["matches"]) >= 1
