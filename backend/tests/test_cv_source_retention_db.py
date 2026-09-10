"""Real PostgreSQL: inputs of unusable generations are retired, live ones never.

Until 09.2026 a failed generation kept the candidate's full CV, screening notes
and Champion in object storage for good. The sweep may only take inputs no
result can read again: the approval source review and the version map re-read
the frozen input of every READY document.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.client import Client, ClientStatus
from app.models.client_cv_rule_preview import ClientCvRulePreview
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generation_job import CvGenerationJob
from app.models.cv_source_cleanup import CvSourceCleanup
from app.services import cv_source_cleanup as cleanup

# A year no other fixture uses: the sweep reads the whole table, and this keeps
# its cutoff (NOW - 7 days) from reaching rows written by other test files.
NOW = datetime(1991, 6, 1, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=30)
RECENT = NOW - timedelta(days=2)


def _document(status: str) -> CvGeneratedDocument:
    return CvGeneratedDocument(
        candidate_name="Synthetic Retention",
        filename=f"cv-{uuid4().hex}.docx",
        status=status,
    )


async def _seed() -> dict:
    """One job per case; returns {case: (job_id, original_key)} plus owners."""
    cases: dict = {}
    async with AsyncSessionLocal() as db:
        client = Client(
            name=f"Retention {uuid4().hex}", status=ClientStatus.active, hidden=False
        )
        db.add(client)
        await db.flush()

        async def job(case, *, status, finished, first, second=None, **extra):
            documents = []
            for doc_status in filter(None, (first, second)):
                document = _document(doc_status)
                db.add(document)
                documents.append(document)
            await db.flush()
            key = f"synthetic-retention/{uuid4().hex}"
            row = CvGenerationJob(
                generated_id=documents[0].id if documents else None,
                second_generated_id=documents[1].id if len(documents) > 1 else None,
                kind=extra.pop("kind", "upload"),
                status=status,
                input_storage_key=key,
                input_sha256="a" * 64,
                finished_at=finished,
                **extra,
            )
            db.add(row)
            await db.flush()
            cases[case] = (row.id, key, [d.id for d in documents])

        await job("failed", status="failed", finished=OLD, first="failed")
        await job("interrupted", status="interrupted", finished=OLD, first="failed")
        await job(
            "ready_beside_failed_second",
            status="failed",
            finished=OLD,
            first="ready",
            second="failed",
        )
        await job("complete", status="complete", finished=OLD, first="ready")
        await job("recent_failure", status="failed", finished=RECENT, first="failed")
        await job(
            "queued",
            status="queued",
            finished=None,
            first="processing",
            updated_at=OLD,
        )
        for case, preview_status, job_status in (
            ("preview_done", "ready", "complete"),
            ("preview_running", "processing", "running"),
        ):
            preview = ClientCvRulePreview(
                client_id=client.id, status=preview_status, language="pl"
            )
            db.add(preview)
            await db.flush()
            await job(
                case,
                kind="preview",
                status=job_status,
                finished=OLD,
                first=None,
                preview_id=preview.id,
            )
        await db.commit()
        cases["_client_id"] = client.id
    return cases


async def _cleanup(cases: dict) -> None:
    async with AsyncSessionLocal() as db:
        documents = [
            d for case in cases.values() if isinstance(case, tuple) for d in case[2]
        ]
        keys = [case[1] for case in cases.values() if isinstance(case, tuple)]
        jobs = [case[0] for case in cases.values() if isinstance(case, tuple)]
        await db.execute(delete(CvGenerationJob).where(CvGenerationJob.id.in_(jobs)))
        await db.execute(
            delete(CvGeneratedDocument).where(CvGeneratedDocument.id.in_(documents))
        )
        await db.execute(
            delete(CvSourceCleanup).where(CvSourceCleanup.storage_key.in_(keys))
        )
        await db.execute(delete(Client).where(Client.id == cases["_client_id"]))
        await db.commit()


@pytest.fixture
async def seeded():
    cases = await _seed()
    try:
        yield cases
    finally:
        await _cleanup(cases)


RETIRED = {"failed", "interrupted", "preview_done"}
KEPT = {
    "ready_beside_failed_second",
    "complete",
    "recent_failure",
    "queued",
    "preview_running",
}


async def test_sweep_retires_only_inputs_no_result_can_use(seeded):
    async with AsyncSessionLocal() as db:
        await cleanup.retire_unneeded_job_inputs(db, now=NOW, limit=500)

    async with AsyncSessionLocal() as db:
        for case in RETIRED | KEPT:
            job_id, key, _ = seeded[case]
            row = await db.get(CvGenerationJob, job_id)
            intent = await db.get(CvSourceCleanup, key)
            if case in RETIRED:
                assert row.input_storage_key == f"purged/{job_id}", case
                assert intent is not None, f"{case}: deletion was not scheduled"
            else:
                assert row.input_storage_key == key, f"{case}: live input retired"
                assert intent is None, f"{case}: live input scheduled for deletion"


async def test_sweep_is_idempotent(seeded):
    async with AsyncSessionLocal() as db:
        await cleanup.retire_unneeded_job_inputs(db, now=NOW, limit=500)
    async with AsyncSessionLocal() as db:
        second = await cleanup.retire_unneeded_job_inputs(db, now=NOW, limit=500)

    mine = {seeded[case][0] for case in RETIRED | KEPT}
    async with AsyncSessionLocal() as db:
        purged = (
            await db.scalars(
                select(CvGenerationJob.id).where(
                    CvGenerationJob.id.in_(mine),
                    CvGenerationJob.input_storage_key.startswith("purged/"),
                )
            )
        ).all()
    assert set(purged) == {seeded[case][0] for case in RETIRED}
    assert second == 0, "an already retired input was picked up again"


async def test_deletion_loop_removes_the_retired_object(seeded, monkeypatch):
    async with AsyncSessionLocal() as db:
        await cleanup.retire_unneeded_job_inputs(db, now=NOW, limit=500)

    storage = AsyncMock()
    monkeypatch.setattr(cleanup, "run_in_threadpool", storage)
    async with AsyncSessionLocal() as db:
        await cleanup.clean_pending_sources(db, limit=10_000)

    deleted = {call.args[1] for call in storage.await_args_list}
    assert {seeded[case][1] for case in RETIRED} <= deleted
    assert not ({seeded[case][1] for case in KEPT} & deleted)
    async with AsyncSessionLocal() as db:
        for case in RETIRED:
            assert await db.get(CvSourceCleanup, seeded[case][1]) is None


async def test_a_purged_marker_is_never_scheduled_as_an_object():
    db = AsyncMock()
    await cleanup.schedule_source_cleanup(db, "purged/42")
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("enabled", [True, False])
async def test_the_deletion_loop_runs_the_sweep_only_when_enabled(monkeypatch, enabled):
    import asyncio
    from types import SimpleNamespace

    from app.core.config import settings

    monkeypatch.setattr(settings, "CV_JOB_INPUT_RETENTION_ENABLED", enabled)
    sweep = AsyncMock(return_value=0)
    monkeypatch.setattr(cleanup, "retire_unneeded_job_inputs", sweep)
    monkeypatch.setattr(cleanup, "clean_pending_sources", AsyncMock())

    class _Session:
        async def __aenter__(self):
            return object()

        async def __aexit__(self, *args):
            return False

    async def _stop(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(cleanup, "AsyncSessionLocal", lambda: _Session())
    # Only this module's view of asyncio: stop after the first tick.
    monkeypatch.setattr(
        cleanup,
        "asyncio",
        SimpleNamespace(sleep=_stop, CancelledError=asyncio.CancelledError),
    )

    with pytest.raises(asyncio.CancelledError):
        await cleanup.recovery_loop()

    assert sweep.await_count == (1 if enabled else 0)
