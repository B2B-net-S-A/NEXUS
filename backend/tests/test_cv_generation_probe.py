from contextlib import asynccontextmanager
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.core import database
from app.services import object_storage
from app.services.cv_generator_b2b import job_snapshot
from app.services.cv_generator_b2b import source_facts as facts
from app.services.cv_generator_b2b import standalone_service as service


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,status", [("new", "failed"), ("upload", "running"), ("upload", "complete")]
)
async def test_probe_only_reads_the_explicitly_selected_failed_upload(
    monkeypatch, kind, status
):
    db = SimpleNamespace(
        get=AsyncMock(return_value=SimpleNamespace(kind=kind, status=status))
    )

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(database, "AsyncSessionLocal", session)
    download = Mock(side_effect=AssertionError("Source must not be read"))
    monkeypatch.setattr(object_storage, "download_cv", download)
    assert await facts._probe_failed_upload(16, "b" * 16) == {
        "outcome": "wrong_job_scope"
    }
    db.get.assert_awaited_once()
    download.assert_not_called()


@pytest.mark.asyncio
async def test_probe_rejects_other_source_bytes_before_any_generation(monkeypatch):
    job = SimpleNamespace(
        kind="upload",
        status="failed",
        input_storage_key="private",
        input_sha256="hash",
        created_by=1,
    )
    db = SimpleNamespace(get=AsyncMock(return_value=job))

    @asynccontextmanager
    async def session():
        yield db

    monkeypatch.setattr(database, "AsyncSessionLocal", session)
    monkeypatch.setattr(object_storage, "download_cv", lambda key: b"snapshot")
    payload = service.UploadGenerationInput(
        cv_bytes=b"different CV", cv_filename="cv.pdf"
    )
    monkeypatch.setattr(
        job_snapshot,
        "deserialize_job_inputs",
        lambda raw, digest: ("upload", {"payload": payload}),
    )
    generate = Mock(
        side_effect=AssertionError("Other source must not reach generation")
    )
    monkeypatch.setattr(service, "generate_cv_from_uploads", generate)
    expected = hashlib.sha256(b"selected CV").hexdigest()[:16]
    assert await facts._probe_failed_upload(16, expected) == {
        "outcome": "source_fingerprint_mismatch"
    }
    generate.assert_not_called()
