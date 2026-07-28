"""Frozen eligibility, ownership and external-adapter command invariants."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.recruitment_pipeline import PipelineStage
from app.models.recruitment_priority import PriorityOriginKind
from app.models.recruitment_process import ProcessStatus
from app.services import process_backfill
from app.services import recruitment_process_commands as commands
from app.services.priority_work_policy import PriorityWorkReason


def _process(**overrides: object) -> SimpleNamespace:
    defaults: dict[str, object] = {
        "id": 501,
        "candidate_id": 11,
        "job_id": 22,
        "attempt_no": 1,
        "credit_user_id": None,
        "owner_user_id": 40,
        "ownership_confirmed_at": None,
        "ownership_confirmed_by_user_id": None,
        "origin_kind": PriorityOriginKind.assigned,
        "origin_assignment_id": 77,
        "eligibility_assignment_id": 77,
        "priority_compliant_at_open": True,
        "kpi_eligible": True,
        "kpi_eligibility_reason": PriorityWorkReason.assigned.value,
        "kpi_eligibility_decided_at": datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc),
        "current_semantic_state": "verified",
        "workflow_revision_id": None,
        "current_stage_revision_id": None,
        "legacy_current_candidate_stage_id": 900,
        "status": ProcessStatus.open,
        "state_version": 3,
        "source_authority": "live_command",
        "opened_at": datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc),
        "closed_at": None,
        "voided_at": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _stage() -> SimpleNamespace:
    return SimpleNamespace(candidate_id=11, job_id=22)


async def test_accepted_verification_preserves_frozen_true_eligibility_after_supersede(
    monkeypatch,
) -> None:
    process = _process()
    effective_mode = AsyncMock(side_effect=AssertionError("must not re-evaluate mode"))
    current_assignment = AsyncMock(return_value=(None, None, None))
    monkeypatch.setattr(commands, "effective_priority_mode", effective_mode)
    monkeypatch.setattr(
        commands,
        "current_priority_assignment",
        current_assignment,
    )

    result = await commands.record_accepted_verification(
        AsyncMock(),
        stage=_stage(),
        verifier_user_id=88,
        process=process,
    )

    assert result is process
    assert process.credit_user_id == 88
    assert process.owner_user_id == 88
    assert process.kpi_eligible is True
    assert process.origin_assignment_id == 77
    assert process.eligibility_assignment_id == 77
    effective_mode.assert_not_awaited()
    current_assignment.assert_not_awaited()


async def test_accepted_verification_preserves_explicit_false_exception(
    monkeypatch,
) -> None:
    decided_at = datetime(2026, 7, 25, 8, 0, tzinfo=timezone.utc)
    process = _process(
        origin_kind=PriorityOriginKind.approved_exception,
        origin_assignment_id=None,
        eligibility_assignment_id=None,
        kpi_eligible=False,
        kpi_eligibility_decided_at=decided_at,
    )
    current_assignment = AsyncMock()
    monkeypatch.setattr(
        commands,
        "current_priority_assignment",
        current_assignment,
    )

    await commands.record_accepted_verification(
        AsyncMock(),
        stage=_stage(),
        verifier_user_id=88,
        process=process,
    )

    assert process.credit_user_id == 88
    assert process.kpi_eligible is False
    assert process.kpi_eligibility_reason == PriorityWorkReason.approved_exception.value
    assert process.kpi_eligibility_decided_at == decided_at
    current_assignment.assert_not_awaited()


async def test_accepted_verification_keeps_legacy_eligibility_unknown(
    monkeypatch,
) -> None:
    process = _process(
        origin_kind=PriorityOriginKind.legacy,
        origin_assignment_id=None,
        eligibility_assignment_id=None,
        kpi_eligible=None,
        kpi_eligibility_reason="legacy_backfill",
        kpi_eligibility_decided_at=None,
    )
    effective_mode = AsyncMock()
    current_assignment = AsyncMock()
    monkeypatch.setattr(commands, "effective_priority_mode", effective_mode)
    monkeypatch.setattr(
        commands,
        "current_priority_assignment",
        current_assignment,
    )

    await commands.record_accepted_verification(
        AsyncMock(),
        stage=_stage(),
        verifier_user_id=88,
        process=process,
    )

    assert process.credit_user_id == 88
    assert process.kpi_eligible is None
    assert process.eligibility_assignment_id is None
    assert process.kpi_eligibility_decided_at is None
    effective_mode.assert_not_awaited()
    current_assignment.assert_not_awaited()


async def test_accepted_verification_does_not_overwrite_confirmed_handoff_owner() -> (
    None
):
    confirmed_at = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)
    process = _process(
        owner_user_id=99,
        ownership_confirmed_at=confirmed_at,
        ownership_confirmed_by_user_id=5,
    )

    await commands.record_accepted_verification(
        AsyncMock(),
        stage=_stage(),
        verifier_user_id=88,
        process=process,
    )

    assert process.credit_user_id == 88
    assert process.owner_user_id == 99
    assert process.ownership_confirmed_at == confirmed_at
    assert process.ownership_confirmed_by_user_id == 5


async def test_external_inbound_becomes_eligible_from_frozen_origin_assignment(
    monkeypatch,
) -> None:
    process = _process(
        origin_kind=PriorityOriginKind.external_inbound,
        eligibility_assignment_id=None,
        kpi_eligible=None,
        kpi_eligibility_reason=PriorityWorkReason.external_inbound.value,
        kpi_eligibility_decided_at=None,
    )
    effective_mode = AsyncMock()
    current_assignment = AsyncMock(return_value=(None, None, None))
    monkeypatch.setattr(commands, "effective_priority_mode", effective_mode)
    monkeypatch.setattr(
        commands,
        "current_priority_assignment",
        current_assignment,
    )

    await commands.record_accepted_verification(
        AsyncMock(),
        stage=_stage(),
        verifier_user_id=88,
        process=process,
    )

    assert process.credit_user_id == 88
    assert process.kpi_eligible is True
    assert process.origin_assignment_id == 77
    assert process.eligibility_assignment_id == 77
    assert process.kpi_eligibility_reason == PriorityWorkReason.assigned.value
    assert process.kpi_eligibility_decided_at is not None
    effective_mode.assert_not_awaited()
    current_assignment.assert_not_awaited()


async def test_handoff_rejects_closed_process(monkeypatch) -> None:
    process = _process(status=ProcessStatus.closed)
    monkeypatch.setattr(
        commands,
        "_latest_process",
        AsyncMock(return_value=process),
    )
    db = SimpleNamespace(
        scalar=AsyncMock(
            return_value=SimpleNamespace(
                id=99,
                has_any_role=lambda *_roles: True,
            )
        ),
        flush=AsyncMock(),
    )
    actor = SimpleNamespace(
        id=5,
        has_role=lambda _role: True,
    )

    with pytest.raises(HTTPException) as caught:
        await commands.handoff_process(
            db,
            candidate_id=process.candidate_id,
            job_id=process.job_id,
            new_owner_user_id=99,
            actor_user=actor,
        )

    assert caught.value.status_code == 404
    assert process.owner_user_id == 40
    db.flush.assert_not_awaited()


async def test_handoff_rejects_non_operational_owner() -> None:
    db = SimpleNamespace(
        scalar=AsyncMock(
            return_value=SimpleNamespace(
                id=99,
                has_any_role=lambda *_roles: False,
            )
        ),
        flush=AsyncMock(),
    )
    actor = SimpleNamespace(id=5, has_role=lambda _role: True)

    with pytest.raises(HTTPException) as caught:
        await commands.handoff_process(
            db,
            candidate_id=11,
            job_id=22,
            new_owner_user_id=99,
            actor_user=actor,
        )

    assert caught.value.status_code == 422
    db.flush.assert_not_awaited()


async def test_plain_admin_cannot_handoff_without_hor_role() -> None:
    actor = SimpleNamespace(id=5, has_role=lambda _role: False)
    with pytest.raises(HTTPException) as caught:
        await commands.handoff_process(
            SimpleNamespace(),
            candidate_id=11,
            job_id=22,
            new_owner_user_id=99,
            actor_user=actor,
        )
    assert caught.value.status_code == 403


class _Rows:
    def __init__(self, values: list[object]):
        self._values = values

    def scalars(self) -> "_Rows":
        return self

    def all(self) -> list[object]:
        return self._values


async def test_batch_external_sync_preserves_existing_legacy_eligibility() -> None:
    moved_at = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)
    stage = SimpleNamespace(
        id=901,
        candidate_id=11,
        job_id=22,
        moved_at=moved_at,
        stage=PipelineStage.cv_sent,
        external_source="traffit",
    )
    process = _process(
        origin_kind=PriorityOriginKind.legacy,
        origin_assignment_id=None,
        eligibility_assignment_id=None,
        kpi_eligible=None,
        kpi_eligibility_reason="legacy_backfill",
        kpi_eligibility_decided_at=None,
        source_authority="backfill",
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Rows([stage.candidate_id]),
                _Rows([SimpleNamespace(id=stage.job_id)]),
                _Rows([stage]),
                _Rows([process]),
            ]
        ),
        flush=AsyncMock(),
    )

    synced = await commands.sync_external_observed_processes(
        db,
        pairs=[(11, 22), (11, 22)],
    )

    assert synced == 1
    assert process.origin_kind is PriorityOriginKind.legacy
    assert process.kpi_eligible is None
    assert process.eligibility_assignment_id is None
    assert process.kpi_eligibility_decided_at is None
    assert process.legacy_current_candidate_stage_id == stage.id
    db.flush.assert_awaited_once()


async def test_external_sync_does_not_reopen_voided_attempt_from_history_replay(
    monkeypatch,
) -> None:
    voided_at = datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
    process = _process(
        status=ProcessStatus.voided,
        closed_at=voided_at,
        voided_at=voided_at,
        legacy_current_candidate_stage_id=None,
    )
    stage = SimpleNamespace(
        id=901,
        candidate_id=11,
        job_id=22,
        moved_at=datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc),
        moved_by=None,
        stage=PipelineStage.cv_sent,
        external_source="traffit",
    )
    semantics = commands._StageSemantics(None, None, "recommended", False)
    create_attempt = AsyncMock()
    sync_attempt = AsyncMock()
    lock_pair = AsyncMock(return_value=SimpleNamespace(id=stage.job_id))
    monkeypatch.setattr(commands, "_lock_external_pair", lock_pair)
    monkeypatch.setattr(commands, "_latest_stage", AsyncMock(return_value=stage))
    monkeypatch.setattr(commands, "_latest_process", AsyncMock(return_value=process))
    monkeypatch.setattr(
        commands,
        "_resolve_stage_semantics",
        AsyncMock(return_value={stage.id: semantics}),
    )
    monkeypatch.setattr(commands, "_create_observed_attempt", create_attempt)
    monkeypatch.setattr(commands, "_sync_process_to_stage", sync_attempt)
    db = SimpleNamespace(scalar=AsyncMock(), flush=AsyncMock())

    result = await commands.sync_external_observed_process(
        db,
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
    )

    assert result is process
    assert process.status is ProcessStatus.voided
    assert process.voided_at == voided_at
    create_attempt.assert_not_awaited()
    sync_attempt.assert_not_awaited()
    lock_pair.assert_awaited_once_with(
        db,
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
    )


async def test_new_traffit_milestone_after_void_creates_one_new_attempt(
    monkeypatch,
) -> None:
    voided_at = datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)
    previous = _process(
        status=ProcessStatus.voided,
        closed_at=voided_at,
        voided_at=voided_at,
        legacy_current_candidate_stage_id=900,
    )
    stage = SimpleNamespace(
        id=901,
        candidate_id=11,
        job_id=22,
        moved_at=datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc),
        moved_by=None,
        stage=PipelineStage.cv_sent,
        external_source="traffit",
    )
    semantics = commands._StageSemantics(None, None, "recommended", False)
    new_attempt = _process(
        id=502,
        attempt_no=2,
        status=ProcessStatus.open,
        current_semantic_state=semantics.semantic_key,
        current_stage_revision_id=semantics.stage_revision_id,
        legacy_current_candidate_stage_id=stage.id,
        opened_at=stage.moved_at,
        closed_at=None,
        voided_at=None,
        source_authority="external_observed",
    )
    create_attempt = AsyncMock(return_value=new_attempt)
    sync_attempt = AsyncMock()
    lock_pair = AsyncMock(return_value=SimpleNamespace(id=stage.job_id))
    monkeypatch.setattr(commands, "_lock_external_pair", lock_pair)
    monkeypatch.setattr(commands, "_latest_stage", AsyncMock(return_value=stage))
    monkeypatch.setattr(
        commands,
        "_latest_process",
        AsyncMock(side_effect=[previous, new_attempt]),
    )
    monkeypatch.setattr(
        commands,
        "_resolve_stage_semantics",
        AsyncMock(return_value={stage.id: semantics}),
    )
    monkeypatch.setattr(commands, "_create_observed_attempt", create_attempt)
    monkeypatch.setattr(commands, "_sync_process_to_stage", sync_attempt)
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=SimpleNamespace(id=stage.job_id)),
        flush=AsyncMock(),
    )

    first = await commands.sync_external_observed_process(
        db,
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
    )
    replay = await commands.sync_external_observed_process(
        db,
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
    )

    assert first is new_attempt
    assert replay is new_attempt
    assert create_attempt.await_count == 1
    assert create_attempt.await_args.kwargs["previous_process"] is previous
    sync_attempt.assert_not_awaited()
    assert previous.status is ProcessStatus.voided
    assert previous.voided_at == voided_at
    assert lock_pair.await_count == 2


def test_external_sync_locks_candidate_then_job_before_process_snapshot() -> None:
    single_source = inspect.getsource(commands.sync_external_observed_process)
    batch_source = inspect.getsource(commands.sync_external_observed_processes)
    lock_source = inspect.getsource(commands._lock_external_pair)

    assert lock_source.index("select(Candidate.id)") < lock_source.index("select(Job)")
    assert lock_source.count(".with_for_update()") == 2
    assert single_source.index("_lock_external_pair") < single_source.index(
        "_latest_stage"
    )
    assert batch_source.index("select(Candidate.id)") < batch_source.index(
        "select(Job)"
    )
    assert batch_source.index("select(Job)") < batch_source.index(
        "select(CandidateStage)"
    )
    assert batch_source.index("select(CandidateStage)") < batch_source.index(
        "select(RecruitmentProcess)"
    )
    assert batch_source.count(".with_for_update()") >= 3


async def test_live_command_resolves_published_custom_stage_semantics() -> None:
    stage = SimpleNamespace(
        id=901,
        stage_def_id=123,
        stage=PipelineStage.new,
    )
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                _Rows([(123, 456, "feedback_pending", 789, False)]),
                _Rows([(123, None, False, 789)]),
            ]
        )
    )

    resolved = await commands._resolve_stage_semantics(db, [stage])

    assert resolved[901].stage_revision_id == 456
    assert resolved[901].workflow_revision_id == 789
    assert resolved[901].semantic_key == "feedback_pending"
    assert resolved[901].is_terminal is False


def test_batch_process_lock_query_does_not_combine_distinct_with_for_update() -> None:
    source = inspect.getsource(commands.sync_external_observed_processes)
    tree = ast.parse(source)
    process_rows = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "process_rows"
            for target in node.targets
        )
    )
    query_source = ast.get_source_segment(source, process_rows) or ""
    assert ".with_for_update()" in query_source
    assert ".distinct(" not in query_source


def _awaited_call_name(node: ast.Await) -> str | None:
    call = node.value
    if not isinstance(call, ast.Call):
        return None
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        if (
            call.func.attr == "commit"
            and isinstance(call.func.value, ast.Attribute)
            and call.func.value.attr == "db"
        ):
            return "commit"
        return call.func.attr
    return None


def test_traffit_stage_upsert_syncs_process_before_every_commit() -> None:
    importer_path = (
        Path(__file__).resolve().parents[1] / "app/services/traffit/importer.py"
    )
    source = importer_path.read_text()
    tree = ast.parse(source)
    importer = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "TraffitImporter"
    )
    method = next(
        node
        for node in importer.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "import_pipelines"
    )
    method_source = ast.get_source_segment(source, method) or ""

    has_nested_transaction = any(
        isinstance(node, ast.AsyncWith)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "begin_nested"
            for item in node.items
        )
        for node in ast.walk(method)
    )
    assert has_nested_transaction
    assert "INSERT INTO candidate_stages" in method_source

    events: list[tuple[int, str]] = []
    for node in ast.walk(method):
        if not isinstance(node, ast.Await):
            continue
        name = _awaited_call_name(node)
        if name in {"sync_external_observed_processes", "commit"}:
            events.append((node.lineno, name))
    ordered_events = [name for _line, name in sorted(events)]
    assert ordered_events == [
        "sync_external_observed_processes",
        "commit",
        "sync_external_observed_processes",
        "commit",
    ]


def test_backfill_locks_deterministically_and_never_reowns_live_processes() -> None:
    source = inspect.getsource(process_backfill.backfill_recruitment_processes)
    assert "select(Candidate.id)" in source
    assert ".with_for_update()" in source
    assert "RecruitmentProcess.attempt_no.desc()" in source
    assert "existing.setdefault(" in source
    assert 'current.source_authority == "backfill"' in source
    assert "or current.origin_kind == PriorityOriginKind.legacy" not in source
    assert "and current.credit_user_id is None" in source
    assert "backfill_owned and current.owner_user_id is None" in source
    assert source.count("backfill_owned") >= 5


def test_closed_process_is_not_a_priority_continuation() -> None:
    source = inspect.getsource(commands.transition_process)
    assert "previous_process.status == ProcessStatus.open" in source
    assert "ProcessStatus.closed, ProcessStatus.voided" in source


def test_open_process_is_strict_and_idempotent_after_candidate_lock() -> None:
    transition_source = inspect.getsource(commands.transition_process)
    open_source = inspect.getsource(commands.open_process)
    lock_position = transition_source.index("select(Candidate.id)")
    idempotency_position = transition_source.index(
        "if _strict_open and continuation_exists"
    )
    assert lock_position < idempotency_position
    assert "return previous_stage" in transition_source
    assert "_strict_open=True" in open_source


def test_terminal_legacy_gap_is_reconstructed_before_admission_decision() -> None:
    source = inspect.getsource(commands.transition_process)
    reconstruction = source.index("previous_process = await _create_process(")
    continuation = source.index("continuation_exists = (")
    policy = source.index("decision = await assert_priority_work_access(")
    assert reconstruction < continuation < policy
    assert "is_continuation=not previous_semantics.is_terminal" in source


def test_command_locks_candidate_then_job_before_policy() -> None:
    source = inspect.getsource(commands.transition_process)
    candidate_lock = source.index("select(Candidate.id)")
    job_lock = source.index("select(Job)")
    policy = source.index("decision = await assert_priority_work_access(")
    assert candidate_lock < job_lock < policy
    assert ".with_for_update()" in source[job_lock:policy]


def test_pending_verification_decision_uses_candidate_and_stage_locks() -> None:
    source = inspect.getsource(commands._lock_current_pending_verification)
    assert "select(Candidate.id)" in source
    assert "select(CandidateStage)" in source
    assert source.count(".with_for_update()") >= 2
    assert "stage.verification_status != VerificationStatus.pending" in source
