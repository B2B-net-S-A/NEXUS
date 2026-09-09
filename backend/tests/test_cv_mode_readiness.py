from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.cv_generator_b2b import standalone_service as svc
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot


BASE = svc.RecruitmentReadiness(
    stage_id=1,
    job_id=2,
    job_title="Developer",
    stage="screening",
    has_champion=False,
    has_notes=False,
    has_cv=True,
)


@pytest.mark.parametrize("mode", ["basic", "polished"])
def test_neutral_modes_only_require_cv_by_default(mode):
    assert replace(BASE, content_mode=mode).ready


@pytest.mark.parametrize(
    "changes",
    [
        {"content_mode": "tailored"},
        {"required_champion": True},
        {"has_cv": False},
        {"required_notes_min_chars": 100, "notes_chars": 99},
    ],
)
def test_missing_required_input_blocks_readiness(changes):
    row = replace(BASE, **changes)
    assert not row.ready
    assert row.missing_inputs


def test_exact_notes_threshold_is_ready_without_optional_champion():
    assert replace(
        BASE, required_notes_min_chars=100, notes_chars=100, has_notes=True
    ).ready


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "requested,locked,cap,expected",
    [
        ("polished", None, None, "polished"),
        ("tailored", None, "basic", "basic"),
        ("basic", "tailored", None, "tailored"),
        ("basic", "tailored", "polished", "polished"),
    ],
)
async def test_readiness_resolves_published_mode_then_client_cap(
    monkeypatch, requested, locked, cap, expected
):
    client = SimpleNamespace(cv_content_mode_cap=cap, name="Test", display_name=None)
    job = SimpleNamespace(
        id=2,
        client_id=3,
        client=client,
        title="Developer",
        must_skills=[],
        nice_skills=[],
        champion_profile={},
    )
    stage = SimpleNamespace(
        id=1, job_id=2, job=job, stage=None, notes=None, screening_answers={}
    )
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=1)
    values = [[stage], [], [], [], [SimpleNamespace(client_id=3)]]
    db.scalars.side_effect = [
        SimpleNamespace(all=lambda value=value: value) for value in values
    ]
    db.execute.return_value = SimpleNamespace(all=lambda: [])
    monkeypatch.setattr(
        svc, "_candidate_has_supported_cv", AsyncMock(return_value=True)
    )
    rule = CvRuleSnapshot(
        None,
        False,
        None,
        False,
        False,
        content_mode=locked,
        content_mode_locked=bool(locked),
    )
    monkeypatch.setattr(svc, "snapshot_rule", lambda row: rule)
    rows = await svc.list_recruitments_with_readiness(db, 1, content_mode=requested)
    assert rows[0].content_mode == expected
    assert rows[0].ready == (expected != "tailored")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,required_champion,error",
    [
        ("basic", False, None),
        ("polished", False, None),
        ("tailored", False, "no_champion"),
        ("basic", True, "no_champion"),
    ],
)
async def test_worker_matches_mode_readiness_without_notes(
    monkeypatch, mode, required_champion, error
):
    job = SimpleNamespace(
        id=2,
        client_id=None,
        title="Developer",
        requirements=None,
        must_skills=[],
        nice_skills=[],
        champion_profile={},
    )
    stage = SimpleNamespace(candidate_id=1, job=job)
    candidate = SimpleNamespace(id=1, name="Audyt", lastname="Testowy")
    doc = SimpleNamespace(storage_key=None, file_content=b"test", filename="cv.docx")
    db = AsyncMock()
    db.get.return_value = candidate
    db.scalars.side_effect = [
        SimpleNamespace(first=lambda: stage),
        SimpleNamespace(first=lambda: doc),
    ]
    monkeypatch.setattr(svc, "collect_screening_notes_text", AsyncMock(return_value=""))
    sentinel = SimpleNamespace()
    pipeline = Mock(return_value=sentinel)
    monkeypatch.setattr(svc, "_run_generation_pipeline", pipeline)
    rule = CvRuleSnapshot(
        None, False, None, False, False, require_champion=required_champion
    )
    if error:
        with pytest.raises(svc.StandaloneGenerationError) as raised:
            await svc.generate_cv_for_candidate(
                db, candidate_id=1, stage_id=1, content_mode=mode, client_rule=rule
            )
        assert raised.value.code == error
        pipeline.assert_not_called()
    else:
        result = await svc.generate_cv_for_candidate(
            db, candidate_id=1, stage_id=1, content_mode=mode, client_rule=rule
        )
        assert result is sentinel
        assert pipeline.call_args.kwargs["screening_notes_text"] == ""
        assert pipeline.call_args.kwargs["content_mode"] == mode
