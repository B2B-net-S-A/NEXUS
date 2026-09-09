from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

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
