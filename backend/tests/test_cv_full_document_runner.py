import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from scripts import eval_cv_full_documents as runner


@pytest.mark.parametrize("months,matched", [(132, True), (36, False)])
def test_ordinary_pipeline_receives_source_language_notes_rule_and_writes_artifact(
    tmp_path, monkeypatch, months, matched
):
    manifest = runner.prepare(tmp_path)
    case = manifest["cases"][0]
    generate = Mock(
        return_value=SimpleNamespace(
            docx_bytes=b"synthetic-output",
            warnings=[],
            render_payload={"source_facts": {"tenure": {"career_months": months}}},
        )
    )
    monkeypatch.setattr(runner, "generate_cv_from_uploads", generate)
    result = runner.generate_case(case, tmp_path)
    payload = generate.call_args.args[0]
    assert payload.cv_bytes == (tmp_path / case["input_file"]).read_bytes()
    assert payload.language == case["language"]
    assert payload.screening_notes == case["screening_notes"]
    assert result["tenure_matches"] is matched
    assert result["human_accepted"] is None
    assert (tmp_path / result["artifact"]).read_bytes() == b"synthetic-output"


def test_changed_input_stops_before_paid_generation(tmp_path, monkeypatch):
    case = runner.prepare(tmp_path)["cases"][0]
    (tmp_path / case["input_file"]).write_bytes(b"changed")
    generate = Mock()
    monkeypatch.setattr(runner, "generate_cv_from_uploads", generate)
    with pytest.raises(ValueError, match="input changed"):
        runner.generate_case(case, tmp_path)
    generate.assert_not_called()


def test_matching_role_count_does_not_hide_missing_named_source_facts(
    tmp_path, monkeypatch
):
    case = runner.prepare(tmp_path)["cases"][0]
    monkeypatch.setattr(
        runner,
        "generate_cv_from_uploads",
        Mock(
            return_value=SimpleNamespace(
                docx_bytes=b"synthetic",
                warnings=[],
                render_payload={
                    "source_facts": {
                        "document": {
                            "name": "Zofia Testowa",
                            "experience": [
                                {"company": "Wrong employer"},
                                {"company": "Other"},
                            ],
                        }
                    }
                },
            )
        ),
    )
    report = runner.generate_case(case, tmp_path)
    assert report["source_role_count_matches"] is True
    assert report["required_source_facts_preserved"] is False
    assert report["missing_required_source_facts"] == ["Firma Testowa 1"]


async def test_existing_receipt_prevents_replay_even_if_previous_run_incomplete(
    tmp_path, monkeypatch
):
    sha = "a" * 40
    monkeypatch.setenv("GIT_SHA", sha)
    claim = AsyncMock(return_value={"complete": False, "results": []})
    monkeypatch.setattr(runner, "claim_run", claim)
    admission = Mock(side_effect=AssertionError("Must not charge a replay"))
    monkeypatch.setattr(runner, "ai_feature", admission)
    result = await runner.run(
        tmp_path, identity="123-1", expected_sha=sha, limit=2, models="primary"
    )
    assert result == 2
    assert claim.call_args.args[0] == "cv_document_eval:123-1"
    admission.assert_not_called()


async def test_wrong_revision_stops_before_receipt_and_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_SHA", "a" * 40)
    claim = AsyncMock()
    monkeypatch.setattr(runner, "claim_run", claim)
    with pytest.raises(ValueError, match="revision mismatch"):
        await runner.run(
            tmp_path, identity="123-1", expected_sha="b" * 40, limit=2, models="primary"
        )
    claim.assert_not_called()


async def test_cancellation_preserves_admitted_operation_without_success(
    tmp_path, monkeypatch
):
    sha = "a" * 40
    monkeypatch.setenv("GIT_SHA", sha)
    monkeypatch.setenv("CV_B2B_MODEL", "original-model")
    monkeypatch.setenv("CV_B2B_FALLBACK_MODELS", "original-fallback")
    monkeypatch.setattr(runner, "claim_run", AsyncMock(return_value=None))
    checkpoints = []

    async def checkpoint(path, report, key):
        checkpoints.append(deepcopy(report))

    @asynccontextmanager
    async def session():
        yield object()

    @asynccontextmanager
    async def admission(*args):
        yield SimpleNamespace(operation_id="admitted-operation")

    def cancelled(*args):
        raise asyncio.CancelledError()

    monkeypatch.setattr(runner, "checkpoint", checkpoint)
    monkeypatch.setattr(runner, "AsyncSessionLocal", session)
    monkeypatch.setattr(runner, "ai_feature", admission)
    monkeypatch.setattr(runner, "generate_case", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await runner.run(
            tmp_path, identity="124-1", expected_sha=sha, limit=1, models="primary"
        )

    assert checkpoints[-1]["complete"] is False
    assert checkpoints[-1]["results"] == []
    assert checkpoints[-1]["human_accepted"] is None
    assert checkpoints[-1]["in_progress"]["operation_id"] == "admitted-operation"
    assert checkpoints[-1]["in_progress"]["case_id"]
    assert checkpoints[-1]["in_progress"]["requested_model"] == "original-model"
    assert checkpoints[-2]["in_progress"] == checkpoints[-1]["in_progress"]
    assert os.environ["CV_B2B_MODEL"] == "original-model"
    assert os.environ["CV_B2B_FALLBACK_MODELS"] == "original-fallback"


@pytest.mark.parametrize(
    "roles,expected", [(None, False), ([], False), ([{}, {}], True), ([{}], False)]
)
def test_full_source_role_count_cannot_be_replaced_by_displayed_roles(
    tmp_path, monkeypatch, roles, expected
):
    case = next(
        case
        for case in runner.prepare(tmp_path)["cases"]
        if case["scenario"] == "display_limit"
    )
    monkeypatch.setattr(
        runner,
        "generate_cv_from_uploads",
        Mock(
            return_value=SimpleNamespace(
                docx_bytes=b"synthetic",
                warnings=[],
                render_payload={
                    "experience": [{}],
                    "source_facts": {"document": {"experience": roles}},
                },
            )
        ),
    )
    result = runner.generate_case(case, tmp_path)
    assert result["source_role_count_matches"] is expected
    assert result["human_accepted"] is None


@pytest.mark.parametrize("offset", [0, 1])
async def test_finished_run_links_model_artifacts_from_root_report(
    tmp_path, monkeypatch, offset
):
    sha = "a" * 40
    monkeypatch.setenv("GIT_SHA", sha)
    monkeypatch.setenv("CV_B2B_MODEL", "primary-model")
    monkeypatch.setattr(runner, "claim_run", AsyncMock(return_value=None))
    checkpoints = []

    async def checkpoint(path, report, key):
        checkpoints.append(deepcopy(report))

    db = SimpleNamespace(
        scalars=AsyncMock(
            return_value=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        model="primary-model",
                        estimated_cost_usd=0,
                        input_tokens=1,
                        output_tokens=1,
                    )
                ]
            )
        )
    )

    @asynccontextmanager
    async def session():
        yield db

    @asynccontextmanager
    async def admission(*args):
        yield SimpleNamespace(operation_id="synthetic-operation")

    monkeypatch.setattr(runner, "checkpoint", checkpoint)
    monkeypatch.setattr(runner, "AsyncSessionLocal", session)
    monkeypatch.setattr(runner, "ai_feature", admission)
    monkeypatch.setattr(
        runner,
        "generate_cv_from_uploads",
        Mock(
            return_value=SimpleNamespace(
                docx_bytes=b"synthetic",
                warnings=[],
                render_payload={
                    "source_facts": {
                        "tenure": {"career_months": 132},
                        "document": {
                            "name": "Zofia Testowa",
                            "experience": [{"company": "Firma Testowa 1"}, {}],
                        },
                    }
                },
            )
        ),
    )
    assert (
        await runner.run(
            tmp_path,
            identity="125-1",
            expected_sha=sha,
            limit=1,
            models="primary",
            offset=offset,
        )
        == 0
    )
    report = checkpoints[-1]
    assert report["case_offset"] == offset
    assert report["case_limit"] == 1
    assert report["corpus_case_count"] == 40
    assert report["covers_full_corpus"] is False
    assert report["requested_case_ids"] == [
        "career_change-pl" if offset == 0 else "career_change-en"
    ]
    assert [row["case_id"] for row in report["results"]] == report["requested_case_ids"]
    assert report["complete"] is True
    assert report["human_accepted"] is None
    row = report["results"][0]
    assert (tmp_path / row["artifact"]).read_bytes() == b"synthetic"
    assert (tmp_path / row["payload_artifact"]).is_file()
    assert row["artifact"].startswith("model-0/")


@pytest.mark.parametrize("offset,limit", [(-1, 1), (40, 1), (39, 2)])
async def test_invalid_range_stops_before_receipt_or_generation(
    tmp_path, monkeypatch, offset, limit
):
    claim = AsyncMock()
    generate = Mock()
    monkeypatch.setattr(runner, "claim_run", claim)
    monkeypatch.setattr(runner, "generate_cv_from_uploads", generate)
    with pytest.raises(ValueError, match="bounded evaluation"):
        await runner.run(
            tmp_path,
            identity="126-1",
            expected_sha="a" * 40,
            limit=limit,
            models="primary",
            offset=offset,
        )
    claim.assert_not_awaited()
    generate.assert_not_called()
