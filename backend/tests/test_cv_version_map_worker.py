import asyncio
from contextlib import asynccontextmanager
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import cv_version_map_jobs as worker
from app.services.cv_version_map_input import encode_map_input


@pytest.mark.parametrize("case", ["valid", "inactive", "corrupt", "provider_failure"])
async def test_worker_checks_snapshot_before_model_and_records_terminal_result(
    monkeypatch, case
):
    html = "<p>Testy AWS tylko szkoleniowo.</p>"
    version = SimpleNamespace(
        id=7,
        language="pl",
        content_html=html,
        content_sha256=hashlib.sha256(html.encode()).hexdigest(),
    )
    raw, digest = encode_map_input(version, [{"name": "AWS", "kind": "must"}])
    db = AsyncMock()
    db.scalar.return_value = SimpleNamespace(
        user_id=3,
        input_content=raw,
        input_sha256="0" * 64 if case == "corrupt" else digest,
    )
    db.get.side_effect = [version, SimpleNamespace(id=3, is_active=case != "inactive")]

    @asynccontextmanager
    async def session():
        yield db

    async def heartbeat(*args):
        await asyncio.Event().wait()

    monkeypatch.setattr(worker, "AsyncSessionLocal", session)
    monkeypatch.setattr(worker, "claim_map", AsyncMock(return_value="owned-token"))
    monkeypatch.setattr(worker, "renew", heartbeat)
    measure = AsyncMock(
        return_value={"items": []},
        side_effect=RuntimeError("failure") if case == "provider_failure" else None,
    )
    finish = AsyncMock()
    monkeypatch.setattr(worker, "measure", measure)
    monkeypatch.setattr(worker, "finish_map", finish)
    await worker.execute_map(7)
    if case in {"inactive", "corrupt"}:
        measure.assert_not_awaited()
    else:
        measure.assert_awaited_once()
        assert measure.call_args.args[0].public_payload()["why_points"] == [
            "Testy AWS tylko szkoleniowo."
        ]
    assert finish.call_args.args == (db, 7, "owned-token")
    if case == "valid":
        assert finish.call_args.kwargs["result"] == {
            "items": [],
            "snapshot_sha256": digest,
            "content_sha256": version.content_sha256,
        }
    else:
        assert finish.call_args.kwargs["error"] == "mapping_unavailable"


@pytest.mark.parametrize("enabled", [False, True])
async def test_approval_captures_requirements_without_copying_old_evidence(
    monkeypatch, enabled
):
    from app.services.cv_generator_b2b import document_policy

    doc = SimpleNamespace(
        job_id=None,
        requirement_map={
            "items": [
                {
                    "requirement": "AWS",
                    "kind": "must",
                    "note": "OLD CLAIM",
                    "evidence": [{"quote": "OLD TEXT"}],
                },
                {"requirement": "AWS", "kind": "must"},
            ]
        },
    )
    db = AsyncMock()
    db.get.return_value = doc
    version = SimpleNamespace(generated_document_id=11)
    monkeypatch.setattr(
        document_policy, "interactive_client_enabled", AsyncMock(return_value=enabled)
    )
    enqueue = AsyncMock()
    monkeypatch.setattr(worker, "enqueue_version_map", enqueue)
    await worker.schedule_approved_map(db, version, 3)
    if enabled:
        enqueue.assert_awaited_once_with(
            db, version, [{"name": "AWS", "kind": "must"}], 3
        )
    else:
        enqueue.assert_not_awaited()
    db.commit.assert_not_awaited()


async def test_empty_upload_map_recovers_original_requirements(monkeypatch):
    from app.services import cv_review_sources
    from app.services.cv_generator_b2b import document_policy

    doc = SimpleNamespace(id=11, mode="upload", job_id=None, requirement_map=None)
    db = AsyncMock()
    db.get.return_value = doc
    version = SimpleNamespace(generated_document_id=11)
    requirements = [{"name": "AWS", "kind": "must"}]
    recover = AsyncMock(return_value=requirements)
    enqueue = AsyncMock()
    monkeypatch.setattr(
        document_policy, "interactive_client_enabled", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(cv_review_sources, "load_upload_requirements", recover)
    monkeypatch.setattr(worker, "enqueue_version_map", enqueue)
    await worker.schedule_approved_map(db, version, 3)
    recover.assert_awaited_once_with(db, 11)
    enqueue.assert_awaited_once_with(db, version, requirements, 3)
    db.commit.assert_not_awaited()
