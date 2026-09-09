from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api import cv_generator_b2b as api
from app.services.cv_generator_b2b import durable_jobs as jobs
from app.services.cv_generator_b2b.job_snapshot import serialize_job_inputs


@pytest.mark.parametrize("case", ["valid", "corrupt", "already_claimed"])
async def test_executor_uses_persisted_inputs_and_never_replays_claimed_job(
    monkeypatch, case
):
    raw, digest = serialize_job_inputs("upload", {"user_id": 7, "quota_state": None})
    record = SimpleNamespace(
        input_storage_key="private-test-key",
        input_sha256=digest,
        generated_id=11,
        kind="upload",
    )
    document = SimpleNamespace(status="ready")
    db = AsyncMock()
    db.get.side_effect = lambda model, ident: (
        record if model is jobs.CvGenerationJob else document
    )
    manager = Mock(
        __aenter__=AsyncMock(return_value=db), __aexit__=AsyncMock(return_value=None)
    )
    monkeypatch.setattr(jobs, "AsyncSessionLocal", lambda: manager)
    monkeypatch.setattr(
        jobs,
        "claim_job",
        AsyncMock(return_value=None if case == "already_claimed" else "owner"),
    )
    finish = AsyncMock()
    monkeypatch.setattr(jobs, "finish_job", finish)
    download = Mock(return_value=raw + (b"corrupt" if case == "corrupt" else b""))
    monkeypatch.setattr(jobs.object_storage, "download_cv", download)
    worker = AsyncMock()
    monkeypatch.setattr(api, "_run_declared", worker)
    await jobs.execute_job(21)
    if case == "valid":
        worker.assert_awaited_once_with(
            api._run_generate_upload_job, 11, user_id=7, quota_state=None
        )
        assert finish.call_args.kwargs == {"failed": False}
    else:
        worker.assert_not_awaited()
        if case == "already_claimed":
            download.assert_not_called()
            finish.assert_not_awaited()
        else:
            assert finish.call_args.kwargs == {"failed": True}
