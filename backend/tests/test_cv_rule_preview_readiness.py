from dataclasses import replace
from unittest.mock import AsyncMock, Mock
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi import BackgroundTasks

from app.api import client_cv_rules as api
from app.services.cv_generator_b2b.standalone_service import RecruitmentReadiness


READY = RecruitmentReadiness(
    stage_id=1,
    job_id=2,
    job_title="Synthetic",
    stage="verified",
    has_champion=False,
    has_cv=True,
    has_notes=False,
)


async def test_preview_replay_returns_before_source_quota_and_enqueue(monkeypatch):
    from app.services.cv_generator_b2b import request_receipts

    db = AsyncMock()
    db.execute.return_value = Mock(first=Mock(return_value=(3, 4)))
    monkeypatch.setattr(
        api, "_client_or_404", AsyncMock(return_value=SimpleNamespace(id=3))
    )
    access = AsyncMock()
    monkeypatch.setattr(api, "_require_client_rule_access", access)
    preview = SimpleNamespace(id=17)
    reserve = AsyncMock(return_value=(Mock(), preview))
    monkeypatch.setattr(request_receipts, "reserve_request", reserve)
    monkeypatch.setattr(api, "_preview_read", Mock(return_value={"id": 17}))
    source = AsyncMock(side_effect=AssertionError("retry must not reload source"))
    charge = AsyncMock(side_effect=AssertionError("retry must not charge"))
    monkeypatch.setattr(api, "load_candidate_generation_source", source)
    monkeypatch.setattr(api, "check_and_increment", charge)
    background = BackgroundTasks()
    key = str(uuid4())
    result = await api.enqueue_client_cv_rule_preview(
        3,
        api.PreviewRequest(candidate_id=4, stage_id=1, cv_document_id=9, language="pl"),
        SimpleNamespace(id=7),
        background,
        db,
        idempotency_key=key,
    )
    assert result == {"id": 17}
    access.assert_awaited_once()
    assert reserve.call_args.args[2:4] == (key, "preview")
    assert reserve.call_args.args[4]["client_id"] == 3
    source.assert_not_awaited()
    charge.assert_not_awaited()
    assert background.tasks == []
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("fails_at", [None, 0, 1])
async def test_preview_checks_exact_draft_and_unruled_variants(monkeypatch, fails_at):
    checks = []

    async def readiness(db, candidate_id, **kwargs):
        checks.append(kwargs)
        row = READY
        if fails_at == len(checks) - 1:
            row = replace(READY, required_notes_min_chars=100, notes_chars=0)
        return [row]

    monkeypatch.setattr(api, "list_recruitments_with_readiness", readiness)
    recipe = api.ClientCvRulePayload(
        require_screening_notes_min_chars=100,
        content_mode="tailored",
        content_mode_locked=True,
    ).model_dump()
    recipe["cv_content_mode_cap"] = "polished"
    if fails_at is not None:
        with pytest.raises(HTTPException) as error:
            await api._require_preview_inputs(
                AsyncMock(),
                client_id=3,
                candidate_id=4,
                stage_id=1,
                recipe_snapshot=recipe,
            )
        assert error.value.status_code == 422
        assert ("Z regułą" if fails_at == 0 else "Bez reguły") in error.value.detail
        assert len(checks) == fails_at + 1
    else:
        await api._require_preview_inputs(
            AsyncMock(),
            client_id=3,
            candidate_id=4,
            stage_id=1,
            recipe_snapshot=recipe,
        )
        assert len(checks) == 2
        assert checks[1]["rule_overrides"] == {3: None}
        assert checks[1]["content_mode_cap_overrides"] == {3: None}
    draft = checks[0]["rule_overrides"][3]
    assert draft.require_screening_notes_min_chars == 100
    assert draft.content_mode == "tailored" and draft.content_mode_locked
    assert checks[0]["content_mode_cap_overrides"] == {3: "polished"}
