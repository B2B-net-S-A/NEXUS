from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api import cv_generator_b2b as api
from app.services.cv_generator_b2b import durable_jobs as jobs
from app.services.cv_generator_b2b.job_snapshot import serialize_job_inputs


@pytest.mark.parametrize("case", ["valid", "corrupt", "already_claimed"])
@pytest.mark.parametrize("kind", ["upload", "preview"])
async def test_executor_uses_persisted_inputs_and_never_replays_claimed_job(
    monkeypatch, case, kind
):
    raw, digest = serialize_job_inputs(kind, {"user_id": 7, "quota_state": None})
    record = SimpleNamespace(
        input_storage_key="private-test-key",
        second_generated_id=None,
        input_sha256=digest,
        generated_id=11 if kind == "upload" else None,
        preview_id=12 if kind == "preview" else None,
        kind=kind,
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
    from app.api import client_cv_rules

    monkeypatch.setattr(client_cv_rules, "_run_rule_preview_job", worker)
    await jobs.execute_job(21)
    if case == "valid":
        if kind == "upload":
            worker.assert_awaited_once_with(
                api._run_generate_upload_job, 11, user_id=7, quota_state=None
            )
        else:
            worker.assert_awaited_once_with(12, user_id=7, quota_state=None)
        assert finish.call_args.kwargs == {"failed": False}
    else:
        worker.assert_not_awaited()
        if case == "already_claimed":
            download.assert_not_called()
            finish.assert_not_awaited()
        else:
            assert finish.call_args.kwargs == {"failed": True}


async def test_lost_owner_cannot_publish_generated_content(monkeypatch):
    from app.services.cv_generator_b2b.job_leases import owned_job

    db = AsyncMock()
    db.scalar.return_value = None  # Lease expired or belongs to a different worker.
    with owned_job(21, "expired-owner"):
        with pytest.raises(RuntimeError, match="lease lost"):
            await api._finalize_success(db, 11, result=SimpleNamespace())
    db.get.assert_not_awaited()
    statement = db.scalar.call_args.args[0]
    sql = str(statement.compile())
    assert "FOR UPDATE" in sql
    assert "lease_token =" in sql
    assert "lease_expires_at >" in sql


async def test_second_document_is_registered_under_same_owner():
    from app.services.cv_generator_b2b.job_leases import (
        owned_job,
        register_second_document,
    )

    db = AsyncMock()
    record = SimpleNamespace(second_generated_id=None)
    db.scalar.return_value = record
    with owned_job(21, "owner"):
        await register_second_document(db, 12)
        assert record.second_generated_id == 12
        with pytest.raises(RuntimeError, match="already has"):
            await register_second_document(db, 13)
    assert record.second_generated_id == 12
