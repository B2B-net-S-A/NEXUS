"""Gdzie idzie układ CV — część bez bazy (22.11.2026).

- nazwa pliku do klienta: „Nowe CV” = wzór z ``.pdf``, zapis zostaje ``.docx``,
- bot Cpro: zatwierdzona wersja w układzie „Nowe CV” idzie jako PDF tego
  układu (z treści wersji), nie z pliku Word; awaria renderu = 503 bez śladu
  pobrania,
- strona panelu doklejana na końcu PDF-u; awaria = PDF bez zmian,
- wspólny render zatwierdzonej wersji czyta jej zamrożone pola,
- API v1: ``format=pdf`` przy „Nowym CV” = PDF tego układu, ``docx`` zostaje
  klasycznym Wordem, stan CV mówi o układzie.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api import candidate_stage_cv
from app.api import integrations_cpro_bot as routes
from app.api.candidate_stage_cv import clean_cv_filename
from app.core.config import settings
from app.services import client_panel_stamp, cv_layout, cv_new_pdf
from app.services.cpro_bot import runs
from app.services.cv_new_pdf import NewCvPdf, NewCvPdfError


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)


# ── Nazwa pliku ──────────────────────────────────────────────────────────────


def test_filename_for_new_layout_is_the_pattern_with_pdf(flag_on):
    assert cv_layout.filename_for("B2B_Tester_Jan Przykładowy.docx", "new") == (
        "B2B_Tester_Jan Przykładowy.pdf"
    )
    assert cv_layout.filename_for("J. Nowak", "new") == "J. Nowak.pdf"
    assert cv_layout.filename_for("CV.docx", "classic") == "CV.docx"
    assert cv_layout.filename_for(None, "new") is None


def test_filename_stays_word_when_the_flag_is_off(monkeypatch):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", False)
    assert cv_layout.filename_for("CV.docx", "new") == "CV.docx"
    assert cv_layout.is_new("new") is False


def test_manual_rename_accepts_the_pdf_name_and_stores_word():
    assert clean_cv_filename("B2B_Tester.pdf") == "B2B_Tester.docx"
    assert clean_cv_filename("B2B_Tester.PDF ") == "B2B_Tester.docx"
    assert clean_cv_filename("B2B_Tester.docx") == "B2B_Tester.docx"
    assert clean_cv_filename(".pdf") is None


# ── Wspólny render zatwierdzonej wersji ──────────────────────────────────────


@pytest.mark.asyncio
async def test_approved_version_pdf_renders_the_frozen_version(monkeypatch):
    seen: dict = {}

    async def fake_render(content_html, **kwargs):
        seen["html"] = content_html
        seen.update(kwargs)
        return NewCvPdf(b"%PDF-new", True, 10.0, (), ())

    monkeypatch.setattr(cv_new_pdf, "render_new_cv_pdf", fake_render)
    db = SimpleNamespace(
        scalar=AsyncMock(return_value={"highlight_keywords": ["SQL"]}),
        commit=AsyncMock(),
    )
    version = SimpleNamespace(
        content_html="<h1>Tester</h1>",
        language="en",
        template="blind",
        page1_extras={"why": ["A."]},
        consent_content=b"\x89PNG",
        generated_document_id=5,
    )
    result = await cv_new_pdf.approved_version_pdf(db, version)
    assert result.pdf == b"%PDF-new"
    assert seen == {
        "html": "<h1>Tester</h1>",
        "language": "en",
        "template": "blind",
        "fallback": {"highlight_keywords": ["SQL"]},
        "extras": {"why": ["A."]},
        "consent": b"\x89PNG",
        # Wersja bez etapu (stara) — bez miasta i MUST klienta (runda 36).
        "facts": cv_new_pdf.CvFacts(),
    }
    db.commit.assert_awaited_once()


# ── Bot Cpro ─────────────────────────────────────────────────────────────────


@pytest.fixture
def cpro(monkeypatch, flag_on):
    version = SimpleNamespace(
        version=3, docx_content=b"PK-word", cv_layout="new", generated_document_id=None
    )
    csv = SimpleNamespace(
        id=9, candidate_id=102, branded_status="finalized", branded_version=3
    )
    run, token = runs.new_run(
        [
            {
                "ref": 101,
                "offer": {
                    "cv_format": "pdf",
                    "cv_version": 3,
                    "cv_file_name": "Branded_CV.pdf",
                },
            }
        ],
        now=datetime.now(timezone.utc),
        submit=False,
        cards={"101": {"cv_stage_id": 11}},
    )
    run.id = 7
    db = SimpleNamespace(scalar=AsyncMock(return_value=csv), commit=AsyncMock())
    log = AsyncMock()
    audit = Mock()
    revalidate = AsyncMock(return_value=run)
    monkeypatch.setattr(
        candidate_stage_cv,
        "approved_version_for_download",
        AsyncMock(return_value=version),
    )
    monkeypatch.setattr(routes, "log_cv_download", log)
    monkeypatch.setattr(routes.candidate_audit, "record_candidate_audit", audit)
    monkeypatch.setattr(routes, "require_cpro_run_token", revalidate)
    monkeypatch.setattr(
        routes,
        "pdf_from_docx",
        AsyncMock(side_effect=AssertionError("klasyczny PDF przy Nowym CV")),
    )
    return SimpleNamespace(
        version=version,
        run=run,
        token=token,
        db=db,
        log=log,
        audit=audit,
        revalidate=revalidate,
    )


async def _download(ctx):
    return await routes.download_cv.__wrapped__(
        request=SimpleNamespace(headers={"X-Run-Token": ctx.token}),
        stage_id=101,
        run=ctx.run,
        db=ctx.db,
    )


@pytest.mark.asyncio
async def test_cpro_gets_the_new_layout_pdf_of_the_approved_version(cpro, monkeypatch):
    render = AsyncMock(return_value=NewCvPdf(b"%PDF-new", True, 10.0, (), ()))
    monkeypatch.setattr(routes.new_cv_pdf, "approved_version_pdf", render)
    response = await _download(cpro)
    render.assert_awaited_once_with(cpro.db, cpro.version)
    assert response.body == b"%PDF-new"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-cv-layout"] == "new"
    assert "Branded_CV.pdf" in response.headers["content-disposition"]
    cpro.revalidate.assert_awaited_once_with(7, cpro.token, cpro.db)
    assert cpro.log.await_args.kwargs["file_format"] == "pdf"


@pytest.mark.asyncio
async def test_cpro_new_layout_render_failure_is_503_without_a_download(
    cpro, monkeypatch
):
    monkeypatch.setattr(
        routes.new_cv_pdf,
        "approved_version_pdf",
        AsyncMock(side_effect=NewCvPdfError(cv_new_pdf.MSG_RENDER_FAILED)),
    )
    with pytest.raises(HTTPException) as caught:
        await _download(cpro)
    assert caught.value.status_code == 503
    cpro.log.assert_not_called()
    cpro.audit.assert_not_called()
    cpro.revalidate.assert_not_called()


@pytest.mark.asyncio
async def test_cpro_with_the_flag_off_keeps_the_word_pdf(cpro, monkeypatch):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", False)
    monkeypatch.setattr(routes, "pdf_from_docx", AsyncMock(return_value=b"%PDF-word"))
    monkeypatch.setattr(
        routes.new_cv_pdf,
        "approved_version_pdf",
        AsyncMock(side_effect=AssertionError("Nowe CV przy wyłączonej fladze")),
    )
    response = await _download(cpro)
    assert response.body == b"%PDF-word"
    assert response.headers["x-cv-layout"] == "classic"


# ── Strona panelu na końcu PDF-u ─────────────────────────────────────────────


def _blank_pdf(pages: int) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument.new()
    for _ in range(pages):
        document.new_page(595, 842)
    out = io.BytesIO()
    document.save(out)
    document.close()
    return out.getvalue()


def _page_count(pdf: bytes) -> int:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(pdf)
    try:
        return len(document)
    finally:
        document.close()


def test_panel_page_goes_after_the_cv(monkeypatch):
    seen: dict = {}

    def fake_page(url, short_url, expires_at, language):
        seen.update(url=url, short_url=short_url, language=language)
        return _blank_pdf(1)

    monkeypatch.setattr(client_panel_stamp, "_panel_page_pdf", fake_page)
    out = client_panel_stamp.append_panel_page(
        _blank_pdf(2),
        "https://example.test/p/abc",
        "example.test/p/abc",
        None,
        language="en",
    )
    assert _page_count(out) == 3
    assert seen == {
        "url": "https://example.test/p/abc",
        "short_url": "example.test/p/abc",
        "language": "en",
    }


def test_panel_page_failure_returns_the_cv_unchanged(monkeypatch):
    original = _blank_pdf(1)

    def broken(*args, **kwargs):
        raise OSError("brak bibliotek renderera")

    monkeypatch.setattr(client_panel_stamp, "_panel_page_pdf", broken)
    assert client_panel_stamp.append_panel_page(original, "u", "s", None) == original


def test_panel_page_html_carries_the_frame_information():
    html = client_panel_stamp._panel_page_html(
        "https://example.test/p/abc?x=<1>",
        "example.test/p/abc",
        datetime(2026, 12, 31, 12, tzinfo=timezone.utc),
        "pl",
    )
    assert "Panel tej rekrutacji" in html
    assert "example.test/p/abc" in html
    assert "31.12.2026" in html
    assert "data:image/svg+xml" in html
    # Adres trafia do HTML-a renderera zeskejpowany.
    assert "<1>" not in html


# ── API v1 (atrapa sesji, jak `test_integrations_v1_cv`) ────────────────────


async def test_v1_pdf_of_a_new_layout_version_is_the_new_cv(flag_on, monkeypatch):
    from app.api.integrations_v1 import cv as v1_cv
    from app.services import integration_cv
    from tests.test_integrations_v1_cv import V1, _call, _csv, _pair_mocks, _wired_app

    db = AsyncMock()
    db.add = Mock()
    db.info = {}
    _pair_mocks(monkeypatch)
    csv = _csv(id=17, branded_status="finalized", branded_version=3, cv_layout="new")
    version = SimpleNamespace(
        version=3,
        docx_content=b"PK-word",
        docx_filename="B2B_Tester.docx",
        cv_layout="new",
    )
    monkeypatch.setattr(integration_cv, "pair_stage_cv", AsyncMock(return_value=csv))
    monkeypatch.setattr(
        candidate_stage_cv,
        "approved_version_for_download",
        AsyncMock(return_value=version),
    )
    render = AsyncMock(return_value=NewCvPdf(b"%PDF-new", True, 10.0, (), ()))
    monkeypatch.setattr(v1_cv.new_cv_pdf, "approved_version_pdf", render)
    monkeypatch.setattr(
        v1_cv, "_pdf", AsyncMock(side_effect=AssertionError("PDF z Worda"))
    )
    log = AsyncMock()
    monkeypatch.setattr(v1_cv, "log_cv_download", log)
    app = _wired_app(monkeypatch, db, {"cv:generate", "candidates:cv"})

    resp = await _call(
        app, "GET", V1 + "/recruitments/4/candidates/2/cv/file?format=pdf"
    )
    assert resp.status_code == 200, resp.text
    assert resp.content == b"%PDF-new"
    assert resp.headers["x-cv-layout"] == "new"
    assert "B2B_Tester.pdf" in resp.headers["content-disposition"]
    render.assert_awaited_once_with(db, version)
    assert log.await_args.kwargs["file_format"] == "pdf"


async def test_v1_docx_of_a_new_layout_version_stays_the_classic_word(
    flag_on, monkeypatch
):
    from app.api.integrations_v1 import cv as v1_cv
    from app.services import integration_cv
    from tests.test_integrations_v1_cv import V1, _call, _csv, _pair_mocks, _wired_app

    db = AsyncMock()
    db.add = Mock()
    db.info = {}
    _pair_mocks(monkeypatch)
    csv = _csv(id=17, branded_status="finalized", branded_version=3, cv_layout="new")
    version = SimpleNamespace(
        version=3,
        docx_content=b"PK-word",
        docx_filename="B2B_Tester.docx",
        docx_sha256="0" * 64,
        content_sha256="1" * 64,
        cv_layout="new",
    )
    monkeypatch.setattr(integration_cv, "pair_stage_cv", AsyncMock(return_value=csv))
    monkeypatch.setattr(
        candidate_stage_cv,
        "approved_version_for_download",
        AsyncMock(return_value=version),
    )
    monkeypatch.setattr(
        v1_cv.new_cv_pdf,
        "approved_version_pdf",
        AsyncMock(side_effect=AssertionError("Word nie ma nowego układu")),
    )
    monkeypatch.setattr(v1_cv, "log_cv_download", AsyncMock())
    app = _wired_app(monkeypatch, db, {"cv:generate", "candidates:cv"})

    resp = await _call(app, "GET", V1 + "/recruitments/4/candidates/2/cv/file")
    assert resp.status_code == 200, resp.text
    assert resp.content.startswith(b"PK")
    assert resp.headers["x-cv-layout"] == "classic"
    assert "B2B_Tester.docx" in resp.headers["content-disposition"]


async def test_v1_new_layout_draft_pdf_checks_the_draft_and_renders_it(
    flag_on, monkeypatch
):
    from app.api.integrations_v1 import cv as v1_cv
    from app.services import integration_cv
    from tests.test_integrations_v1_cv import V1, _call, _csv, _pair_mocks, _wired_app

    db = AsyncMock()
    db.add = Mock()
    db.info = {}
    _pair_mocks(monkeypatch)
    csv = _csv(id=17, branded_version=2, cv_layout="new", branded_draft_html="<p>A</p>")
    monkeypatch.setattr(integration_cv, "pair_stage_cv", AsyncMock(return_value=csv))
    gate = AsyncMock()
    monkeypatch.setattr(candidate_stage_cv, "ensure_draft_downloadable", gate)
    render = AsyncMock(side_effect=NewCvPdfError(cv_new_pdf.MSG_RENDER_FAILED))
    monkeypatch.setattr(v1_cv.new_cv_pdf, "stage_draft_pdf", render)
    log = AsyncMock()
    monkeypatch.setattr(v1_cv, "log_cv_download", log)
    app = _wired_app(monkeypatch, db, {"cv:generate", "candidates:cv"})

    resp = await _call(
        app, "GET", V1 + "/recruitments/4/candidates/2/cv/file?format=pdf"
    )
    assert resp.status_code == 503, resp.text
    gate.assert_awaited_once_with(db, csv)
    render.assert_awaited_once_with(db, csv)
    log.assert_not_awaited()


# ── Panel klienta ────────────────────────────────────────────────────────────


async def test_client_panel_pdf_of_a_new_layout_version(flag_on, monkeypatch):
    from app.services import client_panel

    csv = SimpleNamespace(cv_layout="new", branded_draft_html="<p>A</p>")
    version = SimpleNamespace(cv_layout="new", docx_content=b"PK")
    monkeypatch.setattr(
        client_panel, "_downloadable_cv_row", AsyncMock(return_value=(csv, version))
    )
    render = AsyncMock(return_value=NewCvPdf(b"%PDF-new", True, 10.0, (), ()))
    monkeypatch.setattr(cv_new_pdf, "approved_version_pdf", render)
    db = SimpleNamespace(commit=AsyncMock())
    visible = SimpleNamespace(
        cv=SimpleNamespace(blind=False, filename="B2B_Tester.docx")
    )
    pdf, name = await client_panel.candidate_pdf(db, visible)
    assert (pdf, name) == (b"%PDF-new", "B2B_Tester.pdf")
    render.assert_awaited_once_with(db, version)


async def test_client_panel_draft_in_new_layout_renders_the_draft(flag_on, monkeypatch):
    from app.services import client_panel

    csv = SimpleNamespace(cv_layout="new", branded_draft_html="<p>A</p>")
    monkeypatch.setattr(
        client_panel, "_downloadable_cv_row", AsyncMock(return_value=(csv, None))
    )
    monkeypatch.setattr(
        cv_new_pdf,
        "stage_draft_pdf",
        AsyncMock(side_effect=NewCvPdfError(cv_new_pdf.MSG_RENDER_FAILED)),
    )
    visible = SimpleNamespace(cv=SimpleNamespace(blind=True, filename="x.docx"))
    with pytest.raises(HTTPException) as caught:
        await client_panel.candidate_pdf(SimpleNamespace(commit=AsyncMock()), visible)
    assert caught.value.status_code == 503
    assert "chwilowo niedostępny" in caught.value.detail


async def test_client_panel_classic_version_still_converts_word(flag_on, monkeypatch):
    from app.services import client_panel, cv_pdf_preview

    csv = SimpleNamespace(cv_layout="new", branded_draft_html="")
    version = SimpleNamespace(cv_layout="classic", docx_content=b"PK-word")
    monkeypatch.setattr(
        client_panel, "_downloadable_cv_row", AsyncMock(return_value=(csv, version))
    )
    convert = AsyncMock(return_value=b"%PDF-word")
    monkeypatch.setattr(cv_pdf_preview, "pdf_from_docx", convert)
    monkeypatch.setattr(
        cv_new_pdf,
        "approved_version_pdf",
        AsyncMock(side_effect=AssertionError("wersja klasyczna")),
    )
    visible = SimpleNamespace(cv=SimpleNamespace(blind=False, filename="CV.docx"))
    pdf, name = await client_panel.candidate_pdf(
        SimpleNamespace(commit=AsyncMock()), visible
    )
    assert (pdf, name) == (b"%PDF-word", "CV.pdf")
    convert.assert_awaited_once_with(b"PK-word")
