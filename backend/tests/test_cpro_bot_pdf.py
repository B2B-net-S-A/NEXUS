"""Cpro receives a real branded PDF from the immutable approved Word version."""

from datetime import datetime, timezone
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pdfplumber
import pytest
from fastapi import HTTPException

from app.api import candidate_stage_cv, integrations_cpro_bot as routes
from app.services import cv_pdf_preview
from app.services.cpro_bot import runs
from app.services.cv_approved_docx import render_approved_docx
from app.services.cv_document_assets import default_template


@pytest.fixture
def pdf_route(monkeypatch):
    docx = render_approved_docx(
        "<h1>Cpro PDF Regression</h1>"
        '<h2 data-cv-section="why_points">WHY OUR CANDIDATE?</h2>'
        "<ul><li><p>Over 6 years of practical SQL experience</p></li></ul>",
        default_template(),
    )
    version = SimpleNamespace(version=3, docx_content=docx)
    csv = SimpleNamespace(
        id=9,
        candidate_id=102,
        job_id=103,
        branded_language="en",
        branded_status="finalized",
        branded_version=3,
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
    approved = AsyncMock(return_value=version)
    log = AsyncMock()
    audit = Mock()
    revalidate = AsyncMock(return_value=run)
    monkeypatch.setattr(candidate_stage_cv, "approved_version_for_download", approved)
    monkeypatch.setattr(routes, "log_cv_download", log)
    monkeypatch.setattr(routes.candidate_audit, "record_candidate_audit", audit)
    monkeypatch.setattr(routes, "require_cpro_run_token", revalidate)
    return SimpleNamespace(
        docx=docx,
        version=version,
        csv=csv,
        run=run,
        token=token,
        db=db,
        approved=approved,
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
async def test_actual_cpro_pdf_preserves_branding_and_approved_content(pdf_route):
    if cv_pdf_preview.soffice_path() is None:
        pytest.skip(
            "Real conversion requires LibreOffice; exercised in the backend Docker image"
        )
    response = await _download(pdf_route)
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["x-cv-version"] == "3"
    assert "Branded_CV.pdf" in response.headers["content-disposition"]
    assert response.body.startswith(b"%PDF-") and not response.body.startswith(b"PK")
    assert b"Montserrat" in response.body
    with pdfplumber.open(BytesIO(response.body)) as pdf:
        assert 1 <= len(pdf.pages) <= 2
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        assert "Cpro PDF Regression" in text
        assert "Over 6 years of practical SQL experience" in text
        assert any(page.images for page in pdf.pages), (
            "The corporate letterhead/logo must survive conversion"
        )
    assert pdf_route.log.await_args.kwargs["file_format"] == "pdf"
    pdf_route.revalidate.assert_awaited_once_with(7, pdf_route.token, pdf_route.db)


@pytest.mark.asyncio
async def test_pdf_uses_frozen_approval_after_the_editor_starts_a_new_draft(
    pdf_route, monkeypatch
):
    pdf_route.csv.branded_version = 4
    pdf_route.csv.branded_status = "draft"
    converter = AsyncMock(return_value=b"%PDF-1.7\ntransport fixture")
    monkeypatch.setattr(routes, "pdf_from_docx", converter)
    response = await _download(pdf_route)
    pdf_route.approved.assert_awaited_once_with(pdf_route.db, pdf_route.csv, 3)
    converter.assert_awaited_once_with(pdf_route.docx)
    assert response.headers["x-cv-version"] == "3"


@pytest.mark.asyncio
async def test_pdf_conversion_failure_never_returns_word_or_records_download(
    pdf_route, monkeypatch
):
    monkeypatch.setattr(
        routes,
        "pdf_from_docx",
        AsyncMock(side_effect=cv_pdf_preview.PdfPreviewUnavailable("busy")),
    )
    with pytest.raises(HTTPException) as caught:
        await _download(pdf_route)
    assert caught.value.status_code == 503
    pdf_route.log.assert_not_called()
    pdf_route.audit.assert_not_called()
    pdf_route.revalidate.assert_not_called()


@pytest.mark.asyncio
async def test_token_revoked_during_pdf_conversion_cannot_receive_or_audit_cv(
    pdf_route, monkeypatch
):
    monkeypatch.setattr(
        routes, "pdf_from_docx", AsyncMock(return_value=b"%PDF-1.7\ntransport fixture")
    )
    pdf_route.revalidate.side_effect = HTTPException(401, runs.INVALID_TOKEN_DETAIL)
    with pytest.raises(HTTPException) as caught:
        await _download(pdf_route)
    assert caught.value.status_code == 401
    pdf_route.log.assert_not_called()
    pdf_route.audit.assert_not_called()


@pytest.mark.asyncio
async def test_legacy_snapshot_keeps_word_mime_filename_and_bytes(
    pdf_route, monkeypatch
):
    pdf_route.run.request["items"][0]["offer"] = {"cv_file_name": "Legacy_CV.docx"}
    converter = AsyncMock(
        side_effect=AssertionError("Legacy Word must not be relabelled as PDF")
    )
    monkeypatch.setattr(routes, "pdf_from_docx", converter)
    response = await _download(pdf_route)
    assert response.headers["content-type"] == routes.DOCX_MEDIA_TYPE
    assert response.body.startswith(b"PK")
    assert "Legacy_CV.docx" in response.headers["content-disposition"]
    converter.assert_not_called()
    assert pdf_route.log.await_args.kwargs["file_format"] == "docx"


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [True, "3", 0, -1])
async def test_invalid_frozen_pdf_version_is_rejected_before_delivery(
    pdf_route, monkeypatch, version
):
    pdf_route.run.request["items"][0]["offer"]["cv_version"] = version
    converter = AsyncMock(
        side_effect=AssertionError("Invalid version must not be converted")
    )
    monkeypatch.setattr(routes, "pdf_from_docx", converter)
    with pytest.raises(HTTPException) as caught:
        await _download(pdf_route)
    assert caught.value.status_code == 409
    converter.assert_not_called()
    pdf_route.approved.assert_not_called()
