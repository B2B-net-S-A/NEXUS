"""Both workers attribute the second provider call to its actual admission."""

from datetime import date
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api import cv_generator_b2b as api
from app.services.ai_quota import current_ai_call, declared_call
from app.services.cv_generator_b2b import requirement_map
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from app.services.cv_generator_b2b.standalone_service import GenerationResult
from tests.test_cv_enqueue_sources import source


@pytest.mark.parametrize("mode", ["new", "upload"])
@pytest.mark.parametrize("outcome", ["success", "provider_error", "denied"])
async def test_second_language_uses_its_own_operation_and_restores_parent(
    monkeypatch, mode, outcome
):
    first = api.QuotaState(1, 100, date(2026, 9, 1), str(uuid4()))
    second = api.QuotaState(2, 100, date(2026, 9, 1), str(uuid4()))
    db = AsyncMock()
    db.add = Mock()
    row = SimpleNamespace(
        candidate_id=2,
        job_id=4,
        client_id=5,
        candidate_name="Synthetic Person",
        position="Developer",
        warnings=[],
    )
    db.get.return_value = row
    manager = Mock(
        __aenter__=AsyncMock(return_value=db), __aexit__=AsyncMock(return_value=None)
    )
    monkeypatch.setattr(api, "AsyncSessionLocal", lambda: manager)
    charge = AsyncMock(return_value=second)
    if outcome == "denied":
        charge.side_effect = api.AIQuotaExceeded(
            api.AIFeatureKey.cv_generator, "quota_exceeded", used=100, limit=100
        )
    monkeypatch.setattr(api, "check_and_increment", charge)
    finalize = AsyncMock(return_value=True)
    failure = AsyncMock()
    pending = AsyncMock(return_value=12)
    monkeypatch.setattr(api, "_finalize_success", finalize)
    monkeypatch.setattr(api, "_finalize_failure", failure)
    monkeypatch.setattr(api, "_create_pending_row", pending)
    monkeypatch.setattr(requirement_map, "ensure_requirement_map", AsyncMock())
    seen = []
    facts = object()
    prepare = Mock(return_value=facts)
    monkeypatch.setattr(api, "prepare_source_facts", prepare)

    def render(language):
        seen.append((language, current_ai_call().state))
        if language == "en" and outcome == "provider_error":
            raise api.StandaloneGenerationError(
                "ai_failed", "Synthetic provider failure"
            )
        return GenerationResult(
            candidate_name="Synthetic Person",
            filename="synthetic.docx",
            docx_bytes=b"docx",
            warnings=[],
            processing_time_ms=1,
            render_payload={},
            job_id=4,
        )

    async def generate_source(captured, **kwargs):
        assert kwargs["prepared_source_facts"] is facts
        return render(kwargs["language"])

    def generate_upload(payload, *, prepared_source_facts):
        assert prepared_source_facts is facts
        return render(payload.language)

    monkeypatch.setattr(api, "generate_cv_from_candidate_source", generate_source)
    monkeypatch.setattr(api, "generate_cv_from_uploads", generate_upload)
    monkeypatch.setattr(api, "_upload_requirements", lambda payload: [])
    rule = CvRuleSnapshot(
        filename_pattern=None,
        spaces_to_underscores=True,
        cv_language=None,
        requires_en_copy=True,
        requires_rodo_consent_block=False,
        auto_second_language=True,
    )
    with declared_call(api.AIFeatureKey.cv_generator, user_id=7, state=first):
        if mode == "new":
            await api._run_generate_new_job(
                11,
                candidate_id=2,
                stage_id=3,
                language="pl",
                blind_cv=False,
                user_id=7,
                client_id=5,
                source=source(),
                rule_snapshot=rule,
            )
        else:
            await api._run_generate_upload_job(
                11,
                payload=api.UploadGenerationInput(
                    cv_bytes=b"source", cv_filename="synthetic.docx", client_rule=rule
                ),
                user_id=7,
            )
        assert current_ai_call().state is first
    assert current_ai_call() is None
    prepare.assert_called_once()
    charge.assert_awaited_once_with(db, api.AIFeatureKey.cv_generator, user_id=7)
    assert seen == (
        [("pl", first)] if outcome == "denied" else [("pl", first), ("en", second)]
    )
    assert pending.await_count == (0 if outcome == "denied" else 1)
    assert finalize.await_count == (2 if outcome == "success" else 1)
    assert failure.await_count == (1 if outcome == "provider_error" else 0)
    if outcome == "denied":
        assert any(
            "Druga wersja językowa nie powstała" in warning for warning in row.warnings
        )
