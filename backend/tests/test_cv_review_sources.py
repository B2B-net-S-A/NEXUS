from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import cv_review_sources as service
from app.services.cv_generator_b2b.job_snapshot import serialize_job_inputs
from app.services.cv_generator_b2b.standalone_service import UploadGenerationInput


async def test_review_uses_frozen_upload_and_notes_for_either_language(monkeypatch):
    raw, digest = serialize_job_inputs(
        "upload",
        {
            "payload": UploadGenerationInput(
                cv_bytes=b"original-file",
                cv_filename="original.docx",
                screening_notes="original notes",
            )
        },
    )
    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(
        kind="upload", input_storage_key="snapshot-only", input_sha256=digest
    )
    download = Mock(return_value=raw)
    monkeypatch.setattr(service.object_storage, "download_cv", download)
    result = await service.load_review_source(db, 12)
    assert result.cv_bytes == b"original-file"
    assert result.screening_notes == "original notes"
    assert result.identity == ""  # No generated identity becomes source evidence.
    assert "second_generated_id" in str(db.scalar.call_args.args[0])
    download.assert_called_once_with("snapshot-only")
    db.get.assert_not_awaited()


@pytest.mark.parametrize("missing", [True, False])
async def test_missing_or_modified_snapshot_never_falls_back_to_live_sources(
    monkeypatch, missing
):
    db = AsyncMock()
    db.scalar.return_value = (
        None
        if missing
        else SimpleNamespace(
            kind="upload", input_storage_key="snapshot", input_sha256="a" * 64
        )
    )
    download = Mock(return_value=b"tampered")
    monkeypatch.setattr(service.object_storage, "download_cv", download)
    with pytest.raises(service.ReviewSourceUnavailable):
        await service.load_review_source(db, 12)
    db.get.assert_not_awaited()
    if missing:
        download.assert_not_called()
