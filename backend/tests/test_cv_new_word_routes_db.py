"""Trasy pliku Word CV etapu przy „Nowym CV” (etap 2, decyzja Artura z 25.11.2026).

- „Nowe CV” → Word w nowym wyglądzie (`X-CV-Layout: new`), `?layout=classic` →
  dotychczasowy klasyczny plik; flaga wyłączona → zawsze klasyczny,
- ramka panelu idzie na koniec pliku i tylko przy pobraniu (podgląd bez niej),
- awaria renderu = 503 z polskim komunikatem,
- szkic: ta sama bramka co klasyczny Word (zatwierdzone CV = 409).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.services import cv_new_pdf
from app.services.cv_new_pdf import NewCvDocx, NewCvPdfError
from tests.test_candidate_stage_cv_branded import _seed_draft, _seed_full_stage
from tests.test_cv_layout_handoff_db import HTML
from tests.test_cv_layout_handoff_db import _new_layout_version as _version_only

CLASSIC = b"PK-classic-version"


async def _new_layout_version(sid: int):
    """Zatwierdzona wersja „Nowego CV” z zapisanym klasycznym Wordem — jak po
    prawdziwym zatwierdzeniu (bez niego trasa wersji daje 409)."""
    import hashlib

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.cv_document_version import CvDocumentVersion

    csv = await _version_only(sid)
    async with AsyncSessionLocal() as db:
        version = await db.scalar(
            select(CvDocumentVersion).where(
                CvDocumentVersion.candidate_stage_cv_id == csv.id
            )
        )
        version.docx_content = CLASSIC
        version.docx_sha256 = hashlib.sha256(CLASSIC).hexdigest()
        await db.commit()
    return csv


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)


@pytest.fixture
def fake_word(monkeypatch):
    calls: list[str] = []

    async def stage(db, csv, content_html):
        calls.append("draft")
        return NewCvDocx(b"PK-new-draft", True, 10.0)

    async def approved(db, version):
        calls.append("approved")
        return NewCvDocx(b"PK-new-approved", True, 10.0)

    stamped: list[bool] = []

    async def fake_stamp(
        db, *, job_id, candidate_id, docx, language=None, at_end=False
    ):
        stamped.append(at_end)
        return docx + b"+panel"

    from app.api import candidate_stage_cv

    monkeypatch.setattr(cv_new_pdf, "stage_editor_docx", stage)
    monkeypatch.setattr(cv_new_pdf, "approved_version_docx", approved)
    monkeypatch.setattr(candidate_stage_cv, "stamp_for_download", fake_stamp)
    return calls, stamped


@pytest.mark.asyncio
async def test_approved_new_cv_downloads_the_new_word(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, fake_word
):
    calls, stamped = fake_word
    sid, _, _ = await _seed_full_stage()
    csv = await _new_layout_version(sid)
    url = f"/api/candidates/stages/{sid}/cv/branded/versions/{csv.branded_version}/docx"

    preview = await app_client.get(url, headers=app_auth_headers)
    assert preview.status_code == 200, preview.text
    assert preview.content == b"PK-new-approved"
    assert preview.headers["x-cv-layout"] == "new"
    assert stamped == []

    download = await app_client.get(
        url, params={"intent": "download", "surface": "card"}, headers=app_auth_headers
    )
    assert download.status_code == 200, download.text
    assert download.content == b"PK-new-approved+panel"
    assert stamped == [True], "ramka panelu na końcu pliku"
    assert "B2B_Tester_Jan.docx" in download.headers["content-disposition"]
    assert "etag" not in download.headers
    assert calls == ["approved", "approved"]


@pytest.mark.asyncio
async def test_classic_word_on_request_and_with_the_flag_off(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, fake_word, monkeypatch
):
    calls, _ = fake_word
    sid, _, _ = await _seed_full_stage()
    csv = await _new_layout_version(sid)
    url = f"/api/candidates/stages/{sid}/cv/branded/versions/{csv.branded_version}/docx"

    classic = await app_client.get(
        url, params={"layout": "classic"}, headers=app_auth_headers
    )
    assert classic.status_code == 200, classic.text
    assert classic.content == CLASSIC
    assert "x-cv-layout" not in classic.headers
    assert calls == []

    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", False)
    flag_off = await app_client.get(url, headers=app_auth_headers)
    assert flag_off.content == CLASSIC
    assert "x-cv-layout" not in flag_off.headers
    assert calls == []


@pytest.mark.asyncio
async def test_draft_new_cv_word_and_its_refusals(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, fake_word, monkeypatch
):
    calls, stamped = fake_word
    sid, _, _ = await _seed_full_stage()
    await _seed_draft(sid, HTML)
    branded = await app_client.patch(
        f"/api/candidates/stages/{sid}/cv/layout",
        json={"cv_layout": "new"},
        headers=app_auth_headers,
    )
    assert branded.status_code == 200, branded.text
    revision = branded.json()["edit_revision"]
    url = f"/api/candidates/stages/{sid}/cv/branded/preview-docx"
    body = {"content_html": HTML, "expected_revision": revision}

    draft = await app_client.post(
        url,
        params={"intent": "download", "surface": "editor"},
        json=body,
        headers=app_auth_headers,
    )
    assert draft.status_code == 200, draft.text
    assert draft.content == b"PK-new-draft+panel"
    assert draft.headers["x-cv-layout"] == "new"
    assert "SZKIC_" in draft.headers["content-disposition"]
    assert calls == ["draft"] and stamped == [True]

    async def broken(db, csv, content_html):
        raise NewCvPdfError(cv_new_pdf.MSG_DOCX_FAILED)

    monkeypatch.setattr(cv_new_pdf, "stage_editor_docx", broken)
    failed = await app_client.post(url, json=body, headers=app_auth_headers)
    assert failed.status_code == 503
    assert "pliku Word" in failed.json()["detail"]


@pytest.mark.asyncio
async def test_approved_cv_is_not_a_draft_word(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, fake_word
):
    calls, _ = fake_word
    sid, _, _ = await _seed_full_stage()
    csv = await _new_layout_version(sid)
    refused = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/branded/preview-docx",
        json={"content_html": HTML, "expected_revision": csv.edit_revision or 0},
        headers=app_auth_headers,
    )
    assert refused.status_code == 409
    assert calls == []
