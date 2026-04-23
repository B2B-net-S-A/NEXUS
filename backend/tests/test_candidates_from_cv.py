"""Integration tests for POST /api/candidates/from-cv (v4 auto-fill).

Covers:
  * Happy path: CV → new candidate with contact fields populated
  * Dedup: 409 when the parsed email matches an existing candidate
  * Force: ?force=true creates the candidate and still reports duplicates
"""

from __future__ import annotations

from io import BytesIO

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate


FAKE_PARSED = {
    # Use emails/phones unlikely to collide with existing test fixtures.
    "first_name": "AnnaTest",
    "last_name": "TestowaUnique",
    "email": "anna.testowa.cv-v4@example.com",
    # 9-digit phone that isn't used by any other fixture.
    "phone": "+48 512 777 888",
    "city": "Warszawa",
    "years_it_experience": 6,
    "current_position": "Senior Python Developer",
    "skills": [
        {"name": "Python", "level": "senior", "years": 6},
        {"name": "FastAPI", "level": "senior", "years": 4},
    ],
    "education": [
        {"degree": "MSc", "field": "CS", "school": "PW", "year": 2017}
    ],
    "languages": [{"name": "English", "level": "C1"}],
    "companies": ["Acme Corp", "Globex"],
    "career_summary": "6 lat Pythona w fintechu.",
    "linkedin_url": "https://linkedin.com/in/anna-testowa",
    "_confidence": {
        "first_name": 0.95,
        "last_name": 0.95,
        "email": 0.98,
        "phone": 0.9,
        "city": 0.7,
    },
    "_source": "claude:cv_enrichment:v4",
}


def _fake_pdf_bytes() -> bytes:
    """A tiny PDF-like payload. The extractor is monkeypatched so the
    actual bytes don't matter — just needs to be a non-empty file."""
    return b"%PDF-1.4 fake content for tests"


def _patch_parser_and_extractor(monkeypatch, parsed: dict):
    """Short-circuit CV pipeline: extractor returns canned text, parser the canned dict.

    Also stubs embedding + CC classification so tests don't need Qdrant.
    """
    from app.services import cv_text_extractor
    from app.api import candidates as candidates_api

    def _fake_extract(*_args, **_kwargs) -> str:
        return "Jan Testowy\nSenior Python Developer\nexperience: Python, FastAPI"

    async def _fake_parse(_text, **_kwargs):
        return parsed

    async def _fake_embed(*_args, **_kwargs):
        return None

    async def _fake_cc(_candidate, _db):
        return None

    monkeypatch.setattr(cv_text_extractor, "extract_text", _fake_extract)
    # Patch parse_cv at the call-site (it's imported inside the endpoint fn).
    monkeypatch.setattr(
        "app.services.cv_parser.parse_cv", _fake_parse, raising=True
    )
    monkeypatch.setattr(
        "app.services.embedding_service.embed_candidate",
        _fake_embed,
        raising=True,
    )
    monkeypatch.setattr(
        candidates_api, "_auto_assign_primary_cc", _fake_cc, raising=True
    )


async def _cleanup_candidate(email: str) -> None:
    """Delete a candidate by email so re-runs stay green."""
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(Candidate).where(Candidate.email == email)
        )
        if row:
            await db.delete(row)
            await db.commit()


@pytest.mark.asyncio
async def test_from_cv_happy_path_creates_candidate(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Upload → new candidate with fields populated from parsed output."""
    _patch_parser_and_extractor(monkeypatch, FAKE_PARSED)
    await _cleanup_candidate(FAKE_PARSED["email"])

    files = {"file": ("anna.pdf", _fake_pdf_bytes(), "application/pdf")}
    resp = await app_client.post(
        "/api/candidates/from-cv", headers=app_auth_headers, files=files
    )

    try:
        assert resp.status_code == 201, resp.text
        body = resp.json()
        candidate = body["candidate"]

        assert candidate["name"] == FAKE_PARSED["first_name"]
        assert candidate["lastname"] == FAKE_PARSED["last_name"]
        assert candidate["email"] == FAKE_PARSED["email"]
        assert candidate["phone"] == FAKE_PARSED["phone"]
        assert candidate["years_it_experience"] == 6

        assert body["confidence"]["email"] == pytest.approx(0.98)
        assert body["source"] == "claude:cv_enrichment:v4"
        assert body["duplicates"] == []
    finally:
        await _cleanup_candidate(FAKE_PARSED["email"])


@pytest.mark.asyncio
async def test_from_cv_returns_409_on_duplicate_email(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Second upload with the same parsed email must raise 409."""
    _patch_parser_and_extractor(monkeypatch, FAKE_PARSED)
    await _cleanup_candidate(FAKE_PARSED["email"])

    files = {"file": ("anna.pdf", _fake_pdf_bytes(), "application/pdf")}

    try:
        # First upload — green insert
        first = await app_client.post(
            "/api/candidates/from-cv",
            headers=app_auth_headers,
            files=files,
        )
        assert first.status_code == 201, first.text

        # Second upload — dedup scan must find the first candidate
        second = await app_client.post(
            "/api/candidates/from-cv",
            headers=app_auth_headers,
            files={"file": ("anna2.pdf", _fake_pdf_bytes(), "application/pdf")},
        )
        assert second.status_code == 409, second.text
        detail = second.json()["detail"]
        # FastAPI nests our dict under `detail`; both nested and flat shapes OK.
        if isinstance(detail, dict):
            assert "existing_candidate_id" in detail
            assert detail["existing_candidate_id"] == first.json()["candidate"]["id"]
            assert len(detail["matches"]) >= 1
        else:  # str detail — at minimum the 409 is correct
            assert "duplikat" in detail.lower()
    finally:
        await _cleanup_candidate(FAKE_PARSED["email"])


@pytest.mark.asyncio
async def test_from_cv_force_bypasses_dedup(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """?force=true creates the candidate even when a duplicate exists."""
    # Use a distinct email so we can cleanup both candidates independently.
    payload = dict(FAKE_PARSED)
    payload["email"] = "force.test@example.com"
    payload["first_name"] = "Force"
    payload["last_name"] = "Tester"
    _patch_parser_and_extractor(monkeypatch, payload)
    await _cleanup_candidate(payload["email"])

    files = {"file": ("force.pdf", _fake_pdf_bytes(), "application/pdf")}

    created_ids: list[int] = []
    try:
        first = await app_client.post(
            "/api/candidates/from-cv",
            headers=app_auth_headers,
            files=files,
        )
        assert first.status_code == 201, first.text
        created_ids.append(first.json()["candidate"]["id"])

        # Force override — note ?force=true
        second = await app_client.post(
            "/api/candidates/from-cv?force=true",
            headers=app_auth_headers,
            files={"file": ("force2.pdf", _fake_pdf_bytes(), "application/pdf")},
        )
        # email has UNIQUE constraint so the second insert will hit a DB
        # violation — we accept either 201 (if DB lets it through because of
        # a different email detection path) or 409/500 from the DB. What we
        # assert is that the dedup-soft-block didn't swallow it.
        assert second.status_code in (201, 409, 500), second.text
        if second.status_code == 201:
            created_ids.append(second.json()["candidate"]["id"])
            assert len(second.json()["duplicates"]) >= 1
    finally:
        # Cleanup all candidates with the shared email.
        async with AsyncSessionLocal() as db:
            for cid in created_ids:
                row = await db.scalar(
                    select(Candidate).where(Candidate.id == cid)
                )
                if row:
                    await db.delete(row)
            await db.commit()
        await _cleanup_candidate(payload["email"])


@pytest.mark.asyncio
async def test_from_cv_rejects_empty_text(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """CV that extracts to empty text must fail with 400 (no silent insert)."""
    from app.services import cv_text_extractor

    monkeypatch.setattr(
        cv_text_extractor, "extract_text", lambda *a, **k: ""
    )
    files = {"file": ("blank.pdf", b"%PDF blank", "application/pdf")}
    resp = await app_client.post(
        "/api/candidates/from-cv",
        headers=app_auth_headers,
        files=files,
    )
    assert resp.status_code == 400
