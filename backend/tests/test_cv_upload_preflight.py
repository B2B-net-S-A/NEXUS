from io import BytesIO
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock

from docx import Document
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
import pytest

from app.api import cv_generator_b2b as api
from app.models.user import User, UserRole
from app.services.cv_generator_b2b import upload_preflight as preflight
from app.services.cv_generator_b2b.standalone_service import (
    UploadGenerationInput,
    StandaloneGenerationError,
)


@pytest.fixture(autouse=True)
def isolate_rate_limit(monkeypatch):
    # These cases test input/quota ordering, not the shared per-IP limiter.
    monkeypatch.setattr(api.limiter, "enabled", False)


def docx(text="Audyt Testowy. Programista Python."):
    document = Document()
    document.add_paragraph(text)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def pdf(content=True):
    # Minimal real PDF, including offsets, so the test exercises the parser.
    stream = b"BT /F1 12 Tf 20 20 Td (Synthetic CV) Tj ET" if content else b""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    result = b"%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(result)
    result += b"xref\n0 6\n0000000000 65535 f \n"
    result += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    return (
        result
        + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )


@pytest.mark.parametrize(
    "filename,data",
    [
        ("CV.pdf", b""),
        ("CV.txt", b"text"),
        ("CV.docx", b"not zip"),
        ("CV.pdf", b"%PDF-corrupt"),
        ("CV.docx", docx("")),
        ("CV.pdf", pdf(False)),
    ],
)
async def test_invalid_files_do_not_charge_or_enqueue(monkeypatch, filename, data):
    app = FastAPI()
    app.include_router(api.router)
    app.state.limiter = api.limiter
    db = AsyncMock()
    app.dependency_overrides[api.get_db] = lambda: db
    app.dependency_overrides[get_args(api.CandidateWriteAccess)[1].dependency] = (
        lambda: User(id=7, role=UserRole.admin)
    )
    charge, pending, worker = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(api, "_charge_cv_generation_quota", charge)
    monkeypatch.setattr(api, "_create_pending_row", pending)
    monkeypatch.setattr(api, "_run_declared", worker)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/cv-generator/generate-upload", files={"cv_file": (filename, data)}
        )
    assert response.status_code == 422, response.text
    assert "CV:" in response.json()["detail"]
    charge.assert_not_awaited()
    pending.assert_not_awaited()
    worker.assert_not_awaited()
    db.commit.assert_not_awaited()


def test_valid_pdf_and_docx_pass_without_ocr_or_model():
    preflight.validate_upload_inputs(
        UploadGenerationInput(cv_bytes=pdf(), cv_filename="CV.pdf")
    )
    preflight.validate_upload_inputs(
        UploadGenerationInput(cv_bytes=docx(), cv_filename="CV.docx")
    )


def test_image_pdf_is_left_for_ocr_in_the_worker(monkeypatch):
    from PIL import Image
    from unittest.mock import Mock

    output = BytesIO()
    Image.new("RGB", (8, 8), "white").save(output, format="PDF")
    extractor = Mock(
        side_effect=AssertionError("No OCR or text extraction in PDF admission")
    )
    monkeypatch.setattr(preflight, "extract_text_from_file", extractor)
    preflight.validate_upload_inputs(
        UploadGenerationInput(cv_bytes=output.getvalue(), cv_filename="scan.pdf")
    )
    extractor.assert_not_called()


def test_required_unrecognized_champion_blocks_but_manual_requirements_satisfy():
    args = dict(
        cv_bytes=docx(),
        cv_filename="CV.docx",
        champion_bytes=docx("Nieznany układ"),
        champion_filename="Champion.docx",
        client_rule=SimpleNamespace(require_champion=True),
    )
    with pytest.raises(StandaloneGenerationError, match="nie rozpoznano"):
        preflight.validate_upload_inputs(UploadGenerationInput(**args))
    preflight.validate_upload_inputs(
        UploadGenerationInput(**args, must_requirements="Python")
    )
    args["client_rule"] = None
    preflight.validate_upload_inputs(UploadGenerationInput(**args))


def test_size_limit_is_enforced_without_parsing(monkeypatch):
    from app.services.cv_generator_b2b import standalone_service

    monkeypatch.setattr(standalone_service, "_MAX_UPLOAD_BYTES", 10)
    with pytest.raises(StandaloneGenerationError, match="za duży"):
        preflight.validate_upload_inputs(
            UploadGenerationInput(cv_bytes=b"x" * 11, cv_filename="CV.pdf")
        )


def test_broken_optional_champion_is_not_silently_accepted():
    with pytest.raises(StandaloneGenerationError, match="Profil Championa"):
        preflight.validate_upload_inputs(
            UploadGenerationInput(
                cv_bytes=docx(),
                cv_filename="CV.docx",
                champion_bytes=b"broken",
                champion_filename="profile.docx",
            )
        )
