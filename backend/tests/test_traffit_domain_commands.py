"""Unit contracts for Nexus-originated Traffit domain commands.

These tests deliberately replace the transactional outbox writer with an
``AsyncMock``.  They validate the domain payload at the HTTP/worker boundary
without requiring PostgreSQL or making a Traffit request.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, sentinel

import pytest

from app.models.candidate import CandidateStatus
from app.models.note import NoteType
from app.models.recruitment_pipeline import PipelineStage
from app.services.traffit import domain_commands


@pytest.fixture
def enqueue_mock(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    enqueue = AsyncMock(return_value=sentinel.event)
    monkeypatch.setattr(domain_commands, "enqueue_traffit_event", enqueue)
    return enqueue


class _ConflictRecord:
    """Small constructor-compatible stand-in that avoids ORM mapper setup."""

    class _Column:
        def __eq__(self, _other: object) -> "_ConflictRecord._Column":
            return self

        def in_(self, _values: object) -> "_ConflictRecord._Column":
            return self

    entity_type = _Column()
    nexus_entity_id = _Column()
    conflict_type = _Column()
    status = _Column()

    def __init__(self, **values: object) -> None:
        self.__dict__.update(values)


class _SelectStub:
    def where(self, *_criteria: object) -> "_SelectStub":
        return self


def test_jsonable_recursively_normalizes_domain_values() -> None:
    occurred_at = datetime(2026, 7, 14, 10, 30, tzinfo=timezone.utc)

    assert domain_commands.jsonable(
        {
            "status": CandidateStatus.active,
            "available": date(2026, 8, 1),
            "occurred_at": occurred_at,
            "nested": (PipelineStage.screening, {"pl"}),
        }
    ) == {
        "status": "active",
        "available": "2026-08-01",
        "occurred_at": "2026-07-14T10:30:00+00:00",
        "nested": ["screening", ["pl"]],
    }


def test_candidate_snapshot_serializes_only_requested_fields() -> None:
    candidate = SimpleNamespace(
        id=41,
        name="Ada",
        lastname="Lovelace",
        status=CandidateStatus.passive,
        availability_date=date(2026, 9, 1),
        languages=[{"lang": "pl", "level": "C2"}],
        custom_fields={"_SID": "platform"},
    )

    snapshot = domain_commands.candidate_snapshot(
        candidate,
        fields=("name", "status", "availability_date", "languages", "custom_fields"),
    )

    assert snapshot == {
        "name": "Ada",
        "status": "passive",
        "availability_date": "2026-09-01",
        "languages": [{"lang": "pl", "level": "C2"}],
        "custom_fields": {"_SID": "platform"},
    }


@pytest.mark.asyncio
async def test_candidate_create_and_update_emit_json_safe_payloads(
    enqueue_mock: AsyncMock,
) -> None:
    db = sentinel.db
    candidate = SimpleNamespace(
        id=41,
        name="Ada",
        lastname="Lovelace",
        email="ada@example.com",
        status=CandidateStatus.active,
        availability_date=date(2026, 9, 1),
        custom_fields={"_SID": "platform"},
    )

    created = await domain_commands.capture_candidate_created(
        db,
        candidate,
        actor_id=7,  # type: ignore[arg-type]
    )
    assert created is sentinel.event
    create_args = enqueue_mock.await_args
    assert create_args.args[:4] == (db, "candidate.create", "candidate", 41)
    create_fields = create_args.args[4]["fields"]
    assert create_fields["status"] == "active"
    assert create_fields["availability_date"] == "2026-09-01"
    assert create_fields["custom_fields"] == {"_SID": "platform"}
    assert create_args.kwargs == {
        "actor_id": 7,
        "candidate_id": 41,
        "changed_fields": create_fields.keys(),
        "priority": 10,
    }

    enqueue_mock.reset_mock()
    updated = await domain_commands.capture_candidate_updated(
        db,  # type: ignore[arg-type]
        candidate,
        {
            "status": CandidateStatus.passive,
            "availability_date": date(2026, 10, 1),
            "custom_fields": {"_SID": "data"},
        },
        actor_id=8,
    )
    assert updated is sentinel.event
    enqueue_mock.assert_awaited_once_with(
        db,
        "candidate.update",
        "candidate",
        41,
        {
            "fields": {
                "status": "passive",
                "availability_date": "2026-10-01",
                "custom_fields": {"_SID": "data"},
            }
        },
        actor_id=8,
        candidate_id=41,
        changed_fields=dict(
            status="passive",
            availability_date="2026-10-01",
            custom_fields={"_SID": "data"},
        ).keys(),
        priority=10,
    )


@pytest.mark.asyncio
async def test_note_and_file_payloads_are_append_only_and_content_addressed(
    enqueue_mock: AsyncMock,
) -> None:
    db = sentinel.db
    note = SimpleNamespace(
        id=51,
        candidate_id=41,
        content="x" * 2100,
        note_type=NoteType.email,
        supersedes_note_id=50,
    )

    await domain_commands.capture_note_appended(
        db,  # type: ignore[arg-type]
        note,
        actor_id=7,
        author_name="Ada Admin",
        correction=True,
    )
    note_call = enqueue_mock.await_args
    assert note_call.args[:4] == (db, "note.correct", "note", 51)
    note_payload = note_call.args[4]
    assert note_payload["content"].startswith("x" * 2000)
    assert note_payload["content"].endswith("[Podsumowanie skrócone przez NEXUS]")
    assert note_payload["author_name"] == "Ada Admin"
    assert note_payload["note_type"] == "email"
    assert note_payload["supersedes_note_id"] == 50

    enqueue_mock.reset_mock()
    document = SimpleNamespace(
        id=61,
        candidate_id=41,
        filename="cv-v2.pdf",
        content_type="application/pdf",
        content_sha256="a" * 64,
    )
    await domain_commands.capture_file_uploaded(
        db,
        document,
        actor_id=9,  # type: ignore[arg-type]
    )
    enqueue_mock.assert_awaited_once_with(
        db,
        "file.upload",
        "file",
        61,
        {
            "document_id": 61,
            "filename": "cv-v2.pdf",
            "content_type": "application/pdf",
            "content_sha256": "a" * 64,
            "is_public": False,
        },
        actor_id=9,
        candidate_id=41,
        changed_fields=("content_sha256", "filename"),
        priority=20,
    )


@pytest.mark.asyncio
async def test_assignment_is_emitted_only_for_traffit_managed_job(
    enqueue_mock: AsyncMock,
) -> None:
    db = sentinel.db
    stage = SimpleNamespace(id=71, candidate_id=41, job_id=31, stage=PipelineStage.new)
    local_job = SimpleNamespace(
        id=31, title="Local", client_id=1, external_source="manual"
    )

    assert (
        await domain_commands.capture_assignment_added(
            db,
            stage,
            local_job,
            actor_id=7,  # type: ignore[arg-type]
        )
        is None
    )
    enqueue_mock.assert_not_awaited()

    traffit_job = SimpleNamespace(
        id=31,
        title="Traffit role",
        client_id=1,
        external_source="traffit",
        external_id="recruitment-9",
    )
    result = await domain_commands.capture_assignment_added(
        db,
        stage,
        traffit_job,
        actor_id=7,  # type: ignore[arg-type]
    )
    assert result is sentinel.event
    enqueue_mock.assert_awaited_once_with(
        db,
        "assignment.add",
        "candidate_assignment",
        71,
        {"recruitment_id": "recruitment-9"},
        actor_id=7,
        candidate_id=41,
        changed_fields=("recruitment_id",),
        priority=20,
    )


@pytest.mark.asyncio
async def test_stage_move_carries_remote_target_and_shared_base(
    enqueue_mock: AsyncMock,
) -> None:
    db = Mock()
    previous = SimpleNamespace(
        id=70,
        candidate_id=41,
        job_id=31,
        stage=PipelineStage.screening,
        stage_def_id=8,
        moved_at=datetime(2026, 7, 14, 9, tzinfo=timezone.utc),
    )
    db.scalar = AsyncMock(side_effect=["state-verified", previous, "state-screening"])
    job = SimpleNamespace(
        id=31,
        title="Traffit role",
        client_id=1,
        external_source="traffit",
        external_id="recruitment-9",
    )
    stage = SimpleNamespace(
        id=71,
        candidate_id=41,
        job_id=31,
        stage=PipelineStage.verified,
        stage_def_id=9,
        moved_at=datetime(2026, 7, 14, 10, tzinfo=timezone.utc),
    )

    await domain_commands.capture_stage_moved(db, stage, job, actor_id=7)

    enqueue_mock.assert_awaited_once_with(
        db,
        "stage.move",
        "candidate_stage",
        71,
        {
            "recruitment_id": "recruitment-9",
            "state_id": "state-verified",
            "expected_state_id": "state-screening",
            "candidate_stage_id": 71,
        },
        actor_id=7,
        candidate_id=41,
        changed_fields=("stage", "rejection_reason_id"),
        priority=10,
    )


@pytest.mark.asyncio
async def test_rejection_event_requires_explicit_remote_reason_mapping(
    enqueue_mock: AsyncMock,
) -> None:
    db = Mock()
    db.scalar = AsyncMock(side_effect=["state-rejected", None, "reason-44"])
    job = SimpleNamespace(
        id=31,
        title="Traffit role",
        client_id=1,
        external_source="traffit",
        external_id="recruitment-9",
    )
    stage = SimpleNamespace(
        id=72,
        candidate_id=41,
        job_id=31,
        stage=PipelineStage.rejected,
        stage_def_id=10,
        rejection_reason_id=44,
        moved_at=datetime(2026, 7, 14, 10, tzinfo=timezone.utc),
    )

    await domain_commands.capture_stage_moved(db, stage, job, actor_id=7)

    event_payload = enqueue_mock.await_args.args[4]
    assert enqueue_mock.await_args.args[1] == "stage.reject"
    assert event_payload == {
        "recruitment_id": "recruitment-9",
        "state_id": "state-rejected",
        "expected_state_id": None,
        "candidate_stage_id": 72,
        "rejection_id": "reason-44",
        "local_rejection_reason_id": 44,
    }


@pytest.mark.asyncio
async def test_delete_request_is_manual_event_and_rejects_unknown_type(
    enqueue_mock: AsyncMock,
) -> None:
    db = sentinel.db

    result = await domain_commands.capture_delete_requested(
        db,  # type: ignore[arg-type]
        event_type="assignment.remove_requested",
        aggregate_type="candidate_assignment",
        aggregate_id=71,
        candidate_id=41,
        actor_id=7,
        details={"requested_at": date(2026, 7, 14), "job_id": 31},
    )
    assert result is sentinel.event
    enqueue_mock.assert_awaited_once_with(
        db,
        "assignment.remove_requested",
        "candidate_assignment",
        71,
        {"requested_at": "2026-07-14", "job_id": 31},
        actor_id=7,
        candidate_id=41,
        changed_fields=("deletion_requested",),
        priority=10,
    )

    with pytest.raises(ValueError, match="Unsupported manual action event"):
        await domain_commands.capture_delete_requested(
            db,  # type: ignore[arg-type]
            event_type="candidate.hard_delete",
            aggregate_type="candidate",
            aggregate_id=41,
            candidate_id=41,
            actor_id=7,
            details={},
        )


@pytest.mark.asyncio
async def test_manual_action_persists_conflict_without_deleting_entity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(domain_commands, "TraffitSyncConflict", _ConflictRecord)
    monkeypatch.setattr(domain_commands, "select", lambda *_entities: _SelectStub())
    link = SimpleNamespace(
        id=81,
        entity_type="candidate",
        nexus_entity_id=41,
        traffit_entity_id="employee-41",
        candidate_id=41,
        base_snapshot={"email": "old@example.com"},
    )
    db = Mock()
    db.scalar = AsyncMock(side_effect=[None, link])
    db.add = Mock()
    db.flush = AsyncMock()

    conflict = await domain_commands.request_manual_action(
        db,
        entity_type="candidate",
        nexus_entity_id=41,
        candidate_id=41,
        traffit_entity_id=None,
        conflict_type="delete_requested",
        actor_id=7,
        details={"reason": "duplicate"},
        outbox_event_id=123,
    )

    assert isinstance(conflict, _ConflictRecord)
    assert conflict.entity_link_id == 81
    assert conflict.outbox_event_id == 123
    assert conflict.traffit_entity_id == "employee-41"
    assert conflict.base_value == {"email": "old@example.com"}
    assert conflict.nexus_value == {"requested_by": 7, "reason": "duplicate"}
    assert conflict.status == "manual_action_required"
    db.add.assert_called_once_with(conflict)
    db.flush.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_manual_action_reuses_open_request() -> None:
    existing = SimpleNamespace(
        id=91,
        entity_type="file",
        nexus_entity_id=61,
        candidate_id=41,
        conflict_type="delete_requested",
        status="manual_action_required",
    )
    db = Mock()
    db.scalar = AsyncMock(return_value=existing)
    db.add = Mock()
    db.flush = AsyncMock()

    result = await domain_commands.request_manual_action(
        db,
        entity_type="file",
        nexus_entity_id=61,
        candidate_id=41,
        traffit_entity_id="file-61",
        conflict_type="delete_requested",
        actor_id=7,
        details={},
    )

    assert result is existing
    db.add.assert_not_called()
    db.flush.assert_not_awaited()
