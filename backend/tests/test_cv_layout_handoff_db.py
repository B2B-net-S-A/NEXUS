"""Gdzie idzie układ CV — część na bazie (CI, 22.11.2026).

- nazwa pliku do klienta przy „Nowym CV” z ``.pdf``; ręczna zmiana nazwy
  przyjmuje ``.pdf`` i zapisuje nazwę Worda,
- PDF „Nowego CV” pobrany dla klienta dostaje stronę panelu, podgląd — nie,
- reguła klienta: „Układ CV” w recepcie (wersja, diff, kopia), flaga w odczycie,
- zapis samego układu przy zasadach centralnych (``PUT …/cv-rule/layout``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client_cv_rule import ClientCvRule
from app.models.client_cv_rule_event import ClientCvRuleEvent
from app.models.cv_document_version import CvDocumentVersion
from app.services import cv_layout
from app.services.cv_new_pdf import NewCvPdf
from tests.cv_rule_requests import rule_request
from tests.test_candidate_stage_cv_branded import _seed_draft, _seed_full_stage
from tests.test_client_cv_rules_recipe_api import (
    RULE_URL,
    _cleanup,
    _full_payload,
    _headers_for,
    _make_client,
)

HTML = (
    "<h1>Tester – Jan Przykładowy</h1><hr>"
    '<h2 data-cv-section="why_points">Dlaczego nasz kandydat?</h2>'
    "<ul><li>Ponad 8 lat w QA.</li></ul>"
)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)


async def _new_layout_version(sid: int, *, layout: str = "new") -> CandidateStageCV:
    """Zatwierdzona wersja w podanym układzie, z nazwą pliku ze wzoru klienta."""
    await _seed_draft(sid, HTML)
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        csv.cv_layout = layout
        csv.branded_docx_filename = "B2B_Tester_Jan.docx"
        csv.branded_status = "finalized"
        csv.branded_finalized_at = datetime.now(timezone.utc)
        db.add(
            CvDocumentVersion(
                candidate_stage_cv_id=csv.id,
                version=csv.branded_version,
                content_html=HTML,
                content_sha256="0" * 64,
                template="standard",
                language="pl",
                cv_layout=layout,
                docx_filename="B2B_Tester_Jan.docx",
                approved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        return csv


# ── Nazwa pliku i strona panelu ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_new_layout_shows_the_pdf_name_and_rename_keeps_word(
    app_client: AsyncClient, app_auth_headers: dict, flag_on
):
    sid, _, _ = await _seed_full_stage()
    await _new_layout_version(sid)
    got = await app_client.get(
        f"/api/candidates/stages/{sid}/cv/branded", headers=app_auth_headers
    )
    assert got.status_code == 200, got.text
    assert got.json()["current_filename"] == "B2B_Tester_Jan.pdf"
    # Plik Word (zawsze klasyczny) zostaje pod swoją nazwą.
    assert got.json()["docx_filename"] == "B2B_Tester_Jan.docx"

    renamed = await app_client.patch(
        f"/api/candidates/stages/{sid}/cv/branded/filename",
        json={"filename": "Moja_nazwa.pdf"},
        headers=app_auth_headers,
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["filename"] == "Moja_nazwa.pdf"
    assert renamed.json()["pattern_filename"] == "B2B_Tester_Jan.pdf"
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        assert csv.branded_docx_filename == "Moja_nazwa.docx"


@pytest.mark.asyncio
async def test_downloaded_new_pdf_gets_the_panel_page_preview_does_not(
    app_client: AsyncClient, app_auth_headers: dict, flag_on, monkeypatch
):
    from app.api import cv_pdf_preview

    async def fake_render(content_html, **kwargs):
        return NewCvPdf(b"%PDF-new", True, 10.0, (), ())

    stamped: list[bytes] = []

    async def fake_stamp(db, *, job_id, candidate_id, pdf, language=None):
        stamped.append(pdf)
        return pdf + b"+panel"

    monkeypatch.setattr(cv_pdf_preview, "render_new_cv_pdf", fake_render)
    monkeypatch.setattr(cv_pdf_preview, "stamp_pdf_for_download", fake_stamp)
    sid, _, _ = await _seed_full_stage()
    csv = await _new_layout_version(sid)
    url = f"/api/candidates/stages/{sid}/cv/branded/versions/{csv.branded_version}/pdf"

    preview = await app_client.get(url, headers=app_auth_headers)
    assert preview.status_code == 200, preview.text
    assert preview.content == b"%PDF-new"
    assert stamped == []

    download = await app_client.get(
        url, params={"intent": "download", "surface": "card"}, headers=app_auth_headers
    )
    assert download.status_code == 200, download.text
    assert download.content == b"%PDF-new+panel"
    assert "B2B_Tester_Jan.pdf" in download.headers["content-disposition"]


# ── Reguła klienta ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rule_layout_is_versioned_diffed_and_copied(
    app_client: AsyncClient, flag_on
):
    cid = await _make_client(f"Layout rule {uuid.uuid4().hex[:6]}")
    other = await _make_client(f"Layout copy {uuid.uuid4().hex[:6]}")
    try:
        headers = await _headers_for(app_client, "admin")
        first = await rule_request(
            app_client,
            "PUT",
            RULE_URL.format(cid=cid),
            json=_full_payload(cv_layout="new"),
            headers=headers,
        )
        assert first.status_code == 200, first.text
        assert first.json()["cv_layout"] == "new"
        assert first.json()["new_layout_enabled"] is True
        assert first.json()["version"] == 1
        async with AsyncSessionLocal() as db:
            assert await cv_layout.default_for_client(db, cid) == "new"

        back = await rule_request(
            app_client,
            "PUT",
            RULE_URL.format(cid=cid),
            json=_full_payload(cv_layout="classic"),
            headers=headers,
        )
        assert back.status_code == 200, back.text
        assert back.json()["version"] == 2
        history = await app_client.get(
            RULE_URL.format(cid=cid) + "/history", headers=headers
        )
        assert history.json()[0]["changes"]["cv_layout"] == {
            "from": "new",
            "to": "classic",
        }

        await rule_request(
            app_client,
            "PUT",
            RULE_URL.format(cid=cid),
            json=_full_payload(cv_layout="new"),
            headers=headers,
        )
        copied = await rule_request(
            app_client,
            "POST",
            RULE_URL.format(cid=other) + f"/copy-from/{cid}",
            headers=headers,
        )
        assert copied.status_code == 200, copied.text
        assert copied.json()["cv_layout"] == "new"

        overview = await app_client.get("/api/settings/cv-rules", headers=headers)
        assert overview.json()["new_layout_enabled"] is True
    finally:
        await _cleanup([cid, other])


@pytest.mark.asyncio
async def test_layout_route_works_only_under_central_policies(
    app_client: AsyncClient, flag_on, monkeypatch
):
    from app.services.cv_generator_b2b import central_policies

    cid = await _make_client(f"Layout central {uuid.uuid4().hex[:6]}")
    try:
        headers = await _headers_for(app_client, "admin")
        refused = await app_client.put(
            RULE_URL.format(cid=cid) + "/layout",
            json={"cv_layout": "new", "expected_revision": 0},
            headers=headers,
        )
        assert refused.status_code == 409
        assert "Zapisz i włącz regułę" in refused.json()["detail"]

        monkeypatch.setattr(central_policies, "enabled", lambda: True)
        saved = await app_client.put(
            RULE_URL.format(cid=cid) + "/layout",
            json={"cv_layout": "new", "expected_revision": 0},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["cv_layout"] == "new"
        async with AsyncSessionLocal() as db:
            rule = await db.scalar(
                select(ClientCvRule).where(ClientCvRule.client_id == cid)
            )
            assert rule.cv_layout == "new" and rule.confirmed_at is not None
            event = await db.scalar(
                select(ClientCvRuleEvent).where(ClientCvRuleEvent.client_id == cid)
            )
            assert event.changes == {"cv_layout": {"from": "classic", "to": "new"}}
            assert await cv_layout.default_for_client(db, cid) == "new"

        stale = await app_client.put(
            RULE_URL.format(cid=cid) + "/layout",
            json={"cv_layout": "classic", "expected_revision": 0},
            headers=headers,
        )
        assert stale.status_code == 409
    finally:
        await _cleanup([cid])
