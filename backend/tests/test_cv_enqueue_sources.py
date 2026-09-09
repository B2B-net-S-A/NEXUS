"""Admission and both language renders share owned source/policy values."""

from dataclasses import asdict, replace
from datetime import date
from uuid import uuid4
import json
from io import BytesIO
from types import SimpleNamespace
from typing import get_args
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from docx import Document
from httpx import ASGITransport, AsyncClient
import pytest

from app.api import cv_generator_b2b as api
from app.models.user import User, UserRole
from app.services.cv_generator_b2b.champion_builder import ChampionProfileForPrompt
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from app.services.cv_generator_b2b.standalone_service import (
    CandidateGenerationSource,
    GenerationResult,
    StandaloneGenerationError,
)


def source():
    document = Document()
    document.add_paragraph("Synthetic Person. Developer. Python.")
    original = BytesIO()
    document.save(original)
    return CandidateGenerationSource(
        cv_bytes=original.getvalue(),
        cv_filename="synthetic.docx",
        champion_json=json.dumps(
            asdict(ChampionProfileForPrompt(must_have=["Python"]))
        ),
        has_champion=True,
        screening_notes_text="Confirmed source notes",
        source_warnings=(),
        fallback_name="Synthetic Person",
        job_id=4,
        job_title="Developer",
        client_content_mode_cap=None,
        candidate_id=2,
        stage_id=3,
        cv_document_id=9,
        requirements=(("Python", "must"),),
        client_id=5,
    )


@pytest.mark.parametrize("failure", [None, "missing", "corrupt", "changed_context"])
async def test_source_is_captured_before_charge_and_scheduled_as_value(
    monkeypatch, failure
):
    app = FastAPI()
    app.include_router(api.router)
    monkeypatch.setattr(api.limiter, "enabled", False)
    db = AsyncMock()
    candidate = SimpleNamespace(
        id=2, name="Synthetic", lastname="Person", current_position="Developer"
    )
    stage = SimpleNamespace(id=3, candidate_id=2, job_id=4)
    client_row = SimpleNamespace(id=5, cv_content_mode_cap=None)
    db.get.side_effect = lambda model, ident: {
        api.Candidate: candidate,
        api.CandidateStage: stage,
        api.Client: client_row,
    }[model]
    db.execute.return_value = Mock(scalar_one_or_none=Mock(return_value=5))
    app.dependency_overrides[api.get_db] = lambda: db
    app.dependency_overrides[get_args(api.CandidateWriteAccess)[1].dependency] = (
        lambda: User(id=7, role=UserRole.admin)
    )
    monkeypatch.setattr(api, "ensure_job_membership", AsyncMock())
    monkeypatch.setattr(api, "resolve_client_rule", AsyncMock(return_value=None))
    captured = source()
    order = []

    async def load(*args, **kwargs):
        order.append("source")
        if failure == "missing":
            raise StandaloneGenerationError(
                code="cv_not_found", message="Missing source"
            )
        if failure == "changed_context":
            return replace(captured, client_id=999)
        if failure == "corrupt":
            return replace(captured, cv_bytes=b"not a document")
        return captured

    async def charge(*args, **kwargs):
        order.append("charge")

    monkeypatch.setattr(api, "load_candidate_generation_source", load)
    monkeypatch.setattr(api, "_charge_cv_generation_quota", charge)
    pending = AsyncMock(return_value=11)
    worker = AsyncMock()
    monkeypatch.setattr(api, "_create_pending_row", pending)
    from app.services.cv_generator_b2b import durable_jobs

    persisted = AsyncMock(return_value=21)
    monkeypatch.setattr(durable_jobs, "persist_job", persisted)
    monkeypatch.setattr(durable_jobs, "execute_job", worker)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/cv-generator/generate", json={"candidate_id": 2, "stage_id": 3}
        )
    if failure:
        assert response.status_code == (409 if failure == "changed_context" else 422), (
            response.text
        )
        assert order == ["source"]
        pending.assert_not_awaited()
        worker.assert_not_awaited()
    else:
        assert response.status_code == 202, response.text
        assert order == ["source", "charge"]
        assert persisted.call_args.kwargs["inputs"]["source"] is captured
        assert persisted.call_args.kwargs["inputs"]["rule_snapshot"] is None


async def test_second_language_and_requirement_map_do_not_reload_changed_inputs(
    monkeypatch,
):
    from app.services.cv_generator_b2b import requirement_map

    db = AsyncMock()
    db.add = Mock()
    db.get.return_value = SimpleNamespace(
        candidate_name="Synthetic Person", position="Developer"
    )
    manager = Mock(
        __aenter__=AsyncMock(return_value=db), __aexit__=AsyncMock(return_value=None)
    )
    monkeypatch.setattr(api, "AsyncSessionLocal", lambda: manager)
    forbidden = AsyncMock(side_effect=AssertionError("must not reload mutable input"))
    monkeypatch.setattr(api, "resolve_client_rule", forbidden)
    monkeypatch.setattr(api, "load_candidate_generation_source", forbidden)
    captured = source()
    rule = CvRuleSnapshot(
        filename_pattern=None,
        spaces_to_underscores=True,
        cv_language=None,
        requires_en_copy=True,
        requires_rodo_consent_block=False,
        auto_second_language=True,
        version=4,
    )
    generate = AsyncMock(
        return_value=GenerationResult(
            candidate_name="Synthetic Person",
            filename="synthetic.docx",
            docx_bytes=b"docx",
            warnings=[],
            processing_time_ms=1,
            render_payload={},
            job_id=4,
        )
    )
    monkeypatch.setattr(api, "generate_cv_from_candidate_source", generate)
    finalize = AsyncMock(return_value=True)
    monkeypatch.setattr(api, "_finalize_success", finalize)
    monkeypatch.setattr(api, "_create_pending_row", AsyncMock(return_value=12))
    monkeypatch.setattr(
        api,
        "_charge_second_language_or_note",
        AsyncMock(return_value=api.QuotaState(2, 100, date(2026, 9, 1), str(uuid4()))),
    )
    mapping = AsyncMock()
    monkeypatch.setattr(requirement_map, "ensure_requirement_map", mapping)
    facts = object()
    prepare = Mock(return_value=facts)
    monkeypatch.setattr(api, "prepare_source_facts", prepare)
    await api._run_generate_new_job(
        11,
        candidate_id=2,
        stage_id=3,
        language="pl",
        blind_cv=False,
        user_id=7,
        client_id=5,
        source=captured,
        rule_snapshot=rule,
    )
    assert [call.kwargs["language"] for call in generate.call_args_list] == ["pl", "en"]
    assert all(
        call.args == (captured,) and call.kwargs["client_rule"] is rule
        for call in generate.call_args_list
    )
    assert [call.kwargs["rule_version"] for call in finalize.call_args_list] == [4, 4]
    assert mapping.await_count == 2
    assert all(
        call.kwargs["requirements"] == [{"name": "Python", "kind": "must"}]
        for call in mapping.call_args_list
    )
    prepare.assert_called_once()
    assert all(
        call.kwargs["prepared_source_facts"] is facts
        for call in generate.call_args_list
    )
    forbidden.assert_not_awaited()
