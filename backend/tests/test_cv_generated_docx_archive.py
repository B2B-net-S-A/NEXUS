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
