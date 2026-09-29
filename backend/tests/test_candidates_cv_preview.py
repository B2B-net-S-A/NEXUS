"""`POST /api/candidates/cv/preview` + `/from-cv` z polami formularza (29.09.2026).

Okno „Dodaj kandydata” czyta wgrane CV, wypełnia formularz, a zapis bierze
TEN SAM odczyt z pamięci procesu — model płaci raz. Pilnujemy:

- podgląd nie zakłada kandydata,
- podgląd + zapis tym samym plikiem = jedno wywołanie `parse_cv`,
- pola formularza wygrywają z odczytem CV,
- zły e-mail w formularzu = 422 przy polu `email`.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate

pytestmark = pytest.mark.asyncio


def _parsed(unique: str) -> dict:
    return {
        "first_name": "Czytany",
        "last_name": f"ZCv{unique}",
        "email": f"cv-preview-{unique}@example.com",
        "phone": None,
        "city": "Kraków",
        "current_position": "Tester",
        "linkedin_url": None,
        "skills": [{"name": "Python", "level": "mid", "years": 3}],
        "_confidence": {"first_name": 0.9, "email": 0.95},
        "_source": "claude:test",
    }


def _patch_pipeline(monkeypatch, parsed: dict) -> dict[str, int]:
    from app.api import candidates as candidates_api
    from app.services import cv_text_extractor

    calls = {"parse": 0}

    def _fake_extract(*_args, **_kwargs) -> str:
        return "Tester\nPython, pytest"

    async def _fake_parse(_text, **_kwargs):
        calls["parse"] += 1
        return dict(parsed)

    async def _fake_embed(*_args, **_kwargs):
        return None

    async def _fake_cc(_candidate, _db):
        return None

    async def _no_cheap_duplicates(*_args, **_kwargs):
        return []

    monkeypatch.setattr(cv_text_extractor, "extract_text", _fake_extract)
    monkeypatch.setattr("app.services.cv_parser.parse_cv", _fake_parse, raising=True)
    monkeypatch.setattr(
        "app.services.cv_upload_dedup.find_duplicates_without_llm",
        _no_cheap_duplicates,
        raising=True,
    )
    monkeypatch.setattr(
        "app.services.embedding_service.embed_candidate", _fake_embed, raising=True
    )
    monkeypatch.setattr(
        candidates_api, "_auto_assign_primary_cc", _fake_cc, raising=True
    )
    # conftest wyłącza cache odczytu — tu sprawdzamy właśnie jego działanie.
    monkeypatch.setattr(candidates_api, "_CV_PREVIEW_TTL_SECONDS", 1800)
    return calls


async def _count_by_email(email: str) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count(Candidate.id)).where(Candidate.email == email)
            )
            or 0
        )


async def _cleanup(email: str) -> None:
    async with AsyncSessionLocal() as db:
        row = await db.scalar(select(Candidate).where(Candidate.email == email))
        if row is not None:
            await db.delete(row)
            await db.commit()


async def test_preview_fills_the_form_without_creating_a_candidate(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    unique = uuid.uuid4().hex[:8]
    parsed = _parsed(unique)
    _patch_pipeline(monkeypatch, parsed)

    resp = await app_client.post(
        "/api/candidates/cv/preview",
        headers=app_auth_headers,
        files={"file": ("cv.pdf", f"%PDF-1.4 {unique}".encode(), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Czytany"
    assert body["lastname"] == parsed["last_name"]
    assert body["email"] == parsed["email"]
    assert body["city"] == "Kraków"
    assert body["current_position"] == "Tester"
    assert len(body["cv_sha256"]) == 64
    assert await _count_by_email(parsed["email"]) == 0


async def test_preview_then_save_reads_the_cv_once_and_form_wins(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    unique = uuid.uuid4().hex[:8]
    parsed = _parsed(unique)
    calls = _patch_pipeline(monkeypatch, parsed)
    content = f"%PDF-1.4 once {unique}".encode()
    typed_email = f"cv-preview-typed-{unique}@example.com"

    preview = await app_client.post(
        "/api/candidates/cv/preview",
        headers=app_auth_headers,
        files={"file": ("cv.pdf", content, "application/pdf")},
    )
    assert preview.status_code == 200, preview.text

    try:
        saved = await app_client.post(
            "/api/candidates/from-cv",
            headers=app_auth_headers,
            files={"file": ("cv.pdf", content, "application/pdf")},
            data={"name": "Poprawiony", "email": typed_email},
        )
        assert saved.status_code == 201, saved.text
        candidate = saved.json()["candidate"]
        assert candidate["name"] == "Poprawiony"
        assert candidate["lastname"] == parsed["last_name"]
        assert candidate["email"] == typed_email
        assert calls["parse"] == 1
    finally:
        await _cleanup(typed_email)


async def test_invalid_email_in_form_is_a_field_error(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    unique = uuid.uuid4().hex[:8]
    _patch_pipeline(monkeypatch, _parsed(unique))

    resp = await app_client.post(
        "/api/candidates/from-cv",
        headers=app_auth_headers,
        files={
            "file": ("cv.pdf", f"%PDF-1.4 bad {unique}".encode(), "application/pdf")
        },
        data={"email": "to-nie-jest-mail"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["loc"] == ["body", "email"]
