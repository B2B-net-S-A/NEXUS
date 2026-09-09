import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api import cv_generator_b2b as api


@pytest.mark.parametrize("case", ["valid", "corrupt", "missing", "processing"])
async def test_download_uses_exact_stored_bytes_without_rerender(monkeypatch, case):
    raw = b"synthetic-original-docx"
    row = SimpleNamespace(
        id=11,
        filename="test.docx",
        candidate_name="Synthetic",
        status="processing" if case == "processing" else "ready",
        docx_content=None if case == "missing" else raw,
        docx_sha256="bad" if case == "corrupt" else hashlib.sha256(raw).hexdigest(),
    )
    monkeypatch.setattr(api, "_load_generated_document", AsyncMock(return_value=row))
    render = Mock(side_effect=AssertionError("Stored document must not be rerendered"))
    monkeypatch.setattr(api, "rerender_docx_from_payload", render)
    if case == "valid":
        response = await api.download_generated_cv(11, object(), AsyncMock())
        assert response.body == raw
    else:
        with pytest.raises(HTTPException) as error:
            await api.download_generated_cv(11, object(), AsyncMock())
        assert error.value.status_code == 409
    render.assert_not_called()


async def test_finalized_docx_includes_consent_before_being_archived(monkeypatch):
    row = SimpleNamespace(job_id=None)
    db = AsyncMock()
    db.get.return_value = row
    result = SimpleNamespace(
        docx_bytes=b"without-consent",
        render_payload={"name": "Synthetic"},
        candidate_name="Synthetic",
        job_id=None,
        filename="cv.docx",
        warnings=[],
    )
    render = Mock(return_value=b"with-consent")
    monkeypatch.setattr(api, "rerender_docx_from_payload", render)
    consent = {"storage_key": "synthetic-consent"}
    assert await api._finalize_success(
        db, 11, result=result, consent_screenshot=consent
    )
    assert render.call_args.args[0]["consent_screenshot"] == consent
    assert render.call_args.kwargs == {"require_consent": True}
    assert row.docx_content == b"with-consent"
    assert row.docx_sha256 == hashlib.sha256(b"with-consent").hexdigest()
    assert (
        row.render_payload["artifact_provenance"]["generated_docx_sha256"]
        == row.docx_sha256
    )


@pytest.mark.parametrize("image_bytes", [None, b"invalid-image"])
def test_strict_archive_stops_when_consent_cannot_be_loaded(monkeypatch, image_bytes):
    from app.services.cv_generator_b2b import standalone_service as service

    monkeypatch.setattr(
        service,
        "hydrate_consent_screenshot",
        lambda payload: {"consent_screenshot": {"_bytes": image_bytes}},
    )
    render = Mock(side_effect=AssertionError("Incomplete consent reached renderer"))
    monkeypatch.setattr(service, "render_cv_to_bytes", render)
    with pytest.raises((ValueError, OSError)):
        service.rerender_docx_from_payload({}, require_consent=True)
    render.assert_not_called()


async def test_real_archived_docx_keeps_consent_when_storage_later_fails(monkeypatch):
    from io import BytesIO
    from zipfile import ZipFile
    from PIL import Image
    from app.services import object_storage

    image = BytesIO()
    Image.new("RGB", (2, 2), "white").save(image, format="PNG")
    consent_bytes = image.getvalue()
    storage = Mock(return_value=consent_bytes)
    monkeypatch.setattr(object_storage, "download_cv", storage)
    row = SimpleNamespace(id=11, job_id=None)
    db = AsyncMock()
    db.get.return_value = row
    result = SimpleNamespace(
        docx_bytes=b"before-consent",
        render_payload={
            "name": "Synthetic",
            "position": "Tester",
            "why_points": [],
            "experience": [],
            "skills": [],
            "languages": [],
        },
        candidate_name="Synthetic",
        job_id=None,
        filename="synthetic.docx",
        warnings=[],
    )
    assert await api._finalize_success(
        db,
        11,
        result=result,
        consent_screenshot={"storage_key": "synthetic/consent.png"},
    )
    with ZipFile(BytesIO(row.docx_content)) as document:
        assert any(
            document.read(name) == consent_bytes
            for name in document.namelist()
            if name.startswith("word/media/")
        )
    storage.reset_mock(side_effect=True)
    storage.side_effect = OSError("Storage unavailable after finalization")
    monkeypatch.setattr(api, "_load_generated_document", AsyncMock(return_value=row))
    response = await api.download_generated_cv(11, object(), db)
    assert response.body == row.docx_content
    assert hashlib.sha256(response.body).hexdigest() == row.docx_sha256
    storage.assert_not_called()
