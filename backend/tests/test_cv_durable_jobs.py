from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api import cv_generator_b2b as api
from app.services.ai_quota import QuotaState
from app.services.cv_generator_b2b import durable_jobs as jobs
from app.services.cv_generator_b2b.job_snapshot import serialize_job_inputs


@pytest.mark.parametrize("case", ["valid", "corrupt", "already_claimed"])
@pytest.mark.parametrize("kind", ["upload", "preview"])
@pytest.mark.parametrize("stored_quota", [False, True])
async def test_executor_uses_persisted_inputs_and_never_replays_claimed_job(
    monkeypatch, case, kind, stored_quota
):
    raw, digest = serialize_job_inputs(kind, {"user_id": 7, "quota_state": None})
    record = SimpleNamespace(
        input_storage_key="private-test-key",
        second_generated_id=None,
        input_sha256=digest,
        generated_id=11 if kind == "upload" else None,
        preview_id=12 if kind == "preview" else None,
        quota_snapshot={
            "used": 2,
            "limit": 10,
            "period_start": "2026-09-01",
            "operation_id": "original-admission",
        }
        if stored_quota
        else None,
        kind=kind,
    )
    document = SimpleNamespace(status="ready")
    db = AsyncMock()
    db.scalar.return_value = record
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
    expected_quota = (
        QuotaState(2, 10, date(2026, 9, 1), "original-admission")
        if stored_quota
        else None
    )
    if case == "valid":
        if kind == "upload":
            worker.assert_awaited_once_with(
                api._run_generate_upload_job, 11, user_id=7, quota_state=expected_quota
            )
        else:
            worker.assert_awaited_once_with(12, user_id=7, quota_state=expected_quota)
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


def test_live_durable_preview_does_not_report_arbitrary_fifteen_minute_failure():
    from datetime import datetime, timedelta, timezone
    from app.api.client_cv_rules import _preview_read

    row = SimpleNamespace(
        id=12,
        client_id=5,
        candidate_id=2,
        stage_id=3,
        language="pl",
        status="processing",
        error_message=None,
        prompt_block=None,
        with_rule=None,
        without_rule=None,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )
    assert _preview_read(row, durable=True).status == "processing"
    assert _preview_read(row).status == "failed"  # Legacy work has no lease.


@pytest.mark.parametrize("storage_failure", [False, True])
async def test_input_is_saved_before_admission_and_quota_is_persisted(
    monkeypatch, storage_failure
):
    from datetime import date
    from fastapi import HTTPException
    from app.services.ai_quota import QuotaState

    events = []

    def upload(*args):
        events.append("upload")
        if storage_failure:
            raise OSError("storage unavailable")
        return "test-only-new-object"

    async def charge():
        events.append("charge")
        return QuotaState(2, 10, date(2026, 9, 1), "operation")

    monkeypatch.setattr(jobs.object_storage, "upload_cv", upload)
    db = AsyncMock()
    db.add = Mock()
    if storage_failure:
        with pytest.raises(HTTPException) as exc:
            await jobs.persist_job(
                db, kind="upload", generated_id=11, user_id=7, inputs={}, charge=charge
            )
        assert exc.value.status_code == 503
        assert events == ["upload"]
        db.add.assert_not_called()
    else:
        await jobs.persist_job(
            db, kind="upload", generated_id=11, user_id=7, inputs={}, charge=charge
        )
        assert events == ["upload", "charge"]
        assert db.add.call_args.args[0].quota_snapshot == {
            "used": 2,
            "limit": 10,
            "period_start": "2026-09-01",
            "operation_id": "operation",
        }


async def test_rejected_admission_removes_only_new_snapshot(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(
        jobs.object_storage, "upload_cv", Mock(return_value="test-only-new-snapshot")
    )
    delete = Mock()
    monkeypatch.setattr(jobs.object_storage, "delete_cv", delete)
    charge = AsyncMock(side_effect=HTTPException(503, "quota exhausted"))
    db = AsyncMock()
    db.add = Mock()
    with pytest.raises(HTTPException):
        await jobs.persist_job(
            db,
            kind="upload",
            generated_id=11,
            user_id=7,
            inputs={"candidate_source": b"original"},
            charge=charge,
        )
    charge.assert_awaited_once()
    delete.assert_called_once_with("test-only-new-snapshot")
    db.add.assert_not_called()


async def test_expired_worker_does_not_charge_for_second_language(monkeypatch):
    from app.services.cv_generator_b2b.job_leases import owned_job

    db = AsyncMock()
    db.scalar.return_value = None
    charge = AsyncMock()
    monkeypatch.setattr(api, "check_and_increment", charge)
    with owned_job(21, "expired"):
        with pytest.raises(RuntimeError, match="lease lost"):
            await api._charge_second_language_or_note(
                db, first_generated_id=11, user_id=7
            )
    charge.assert_not_awaited()


async def test_failure_includes_secondary_output_without_overwriting_ready_cv():
    db = AsyncMock()
    await jobs.fail_unfinished_outputs(db, 21)
    assert db.execute.await_count == 2
    generated = str(db.execute.call_args_list[0].args[0].compile())
    assert "second_generated_id" in generated
    assert "generated_id" in generated
    assert "status =" in generated
    values = db.execute.call_args_list[0].args[0].compile().params
    assert "processing" in values.values()
    assert "failed" in values.values()
