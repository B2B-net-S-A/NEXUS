from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import HTTPException
import pytest

from app.services.cv_source_erasure import detach_candidate_job_sources


@pytest.mark.parametrize(
    "state", ["queued", "running", "complete", "failed", "interrupted"]
)
async def test_erasure_preserves_active_sources_and_returns_terminal_keys(state):
    jobs = [
        SimpleNamespace(status="complete", input_storage_key="source-a"),
        SimpleNamespace(status=state, input_storage_key="source-b"),
    ]
    db = AsyncMock()
    db.scalars.side_effect = [
        SimpleNamespace(all=lambda: jobs),
        SimpleNamespace(all=lambda: []),
    ]
    if state in {"queued", "running"}:
        with pytest.raises(HTTPException) as error:
            await detach_candidate_job_sources(db, 7)
        assert error.value.status_code == 409
        db.delete.assert_not_awaited()
    else:
        assert await detach_candidate_job_sources(db, 7) == ["source-a", "source-b"]
        assert db.delete.await_count == 2
    sql = str(db.scalars.call_args_list[0].args[0])
    assert "FOR UPDATE" in sql
    assert "second_generated_id" in sql
    assert "client_cv_rule_previews" in sql
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("code", ["55P03", "08006"])
async def test_job_lock_contention_is_retryable_but_other_database_errors_propagate(
    code,
):
    from sqlalchemy.exc import DBAPIError

    class DatabaseFailure(RuntimeError):
        sqlstate = code

    error = DBAPIError("SELECT", {}, DatabaseFailure("database error"), False)
    db = AsyncMock()
    db.scalars.side_effect = error
    with pytest.raises(HTTPException if code == "55P03" else DBAPIError) as caught:
        await detach_candidate_job_sources(db, 7)
    if code == "55P03":
        assert caught.value.status_code == 409
    else:
        assert caught.value is error
    from sqlalchemy.dialects import postgresql

    assert "NOWAIT" in str(
        db.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    )
    db.delete.assert_not_awaited()


@pytest.mark.parametrize(
    "status",
    ["queued", "running", "verified", "rejected", "failed", "interrupted", "cancelled"],
)
async def test_erasure_includes_private_review_inputs(status):
    review = SimpleNamespace(status=status, input_content=b"private source")
    generation = SimpleNamespace(status="complete", input_storage_key="source")
    db = AsyncMock()
    db.scalars.side_effect = [
        SimpleNamespace(all=lambda: [generation]),
        SimpleNamespace(all=lambda: [review]),
    ]
    if status in {"queued", "running"}:
        with pytest.raises(HTTPException) as error:
            await detach_candidate_job_sources(db, 7)
        assert error.value.status_code == 409
        db.delete.assert_not_awaited()
    else:
        assert await detach_candidate_job_sources(db, 7) == ["source"]
        assert [call.args[0] for call in db.delete.await_args_list] == [
            generation,
            review,
        ]
    from sqlalchemy.dialects import postgresql

    sql = str(
        db.scalars.call_args_list[1].args[0].compile(dialect=postgresql.dialect())
    )
    assert "candidate_stage_cvs.candidate_id" in sql
    assert "cv_generated_documents.candidate_id" in sql
    assert "NOWAIT" in sql
    db.commit.assert_not_awaited()
