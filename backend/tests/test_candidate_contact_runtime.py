"""Runtime boundaries for the candidate-global contact queue.

The larger coordination suite proves locking and state transitions.  These
tests focus on the rollout gates and the strict Traffit cursor contract.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.dialects import postgresql

from app.api.candidate_contact import (
    _OWNER_QUEUE_STATES,
    _OVERSIGHT_EXCEPTION_BASE_STATES,
    _OVERSIGHT_REASSIGNMENT_EVENTS,
    _oversight_exception_clause,
    _oversight_priority_expression,
    _oversight_priority_value,
    _queue_priority_expression,
    _reassignment_event_clause,
    get_candidate_contact_status,
)
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_contact import (
    CandidateContactCase,
    CandidateContactOpportunity,
    CandidateContactTraffitCursor,
    CandidateContactTraffitLedger,
)
from app.models.client import Client, ClientStatus
from app.models.job import Job, JobPriority, JobStatus
from app.models.skill import Skill, SkillAlias  # noqa: F401
from app.schemas.candidate import CandidateQuickViewCandidate
from app.services import candidate_contact as candidate_contact_service
from app.services import candidate_contact_coordination as contact_coordination
from app.services.candidate_contact import (
    close_contact_opportunity,
    ensure_contact_opportunity,
)
from app.services.candidate_contact_hooks import (
    maybe_close_contact_opportunity,
    maybe_ensure_contact_opportunity,
    maybe_remove_calendar_handoff,
    maybe_sync_calendar_handoff,
)
from app.services.signing import pipeline_hook as signing_pipeline_hook
from app.tasks import candidate_contact_traffit as contact_traffit_task

BASE_TIME = datetime(2026, 7, 28, 8, 0, tzinfo=timezone.utc)


class _RejectingTraffitClient:
    def __init__(self) -> None:
        self.requests = 0

    async def get_paginated(self, *_args: Any, **_kwargs: Any):
        self.requests += 1
        raise RuntimeError("HTTP 400 unsupported X-Request-Filter")
        yield {}  # pragma: no cover - keeps this an async generator


class _StaticTraffitClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.requests = 0

    async def get_paginated(self, *_args: Any, **_kwargs: Any):
        self.requests += 1
        for row in self.rows:
            yield row


async def test_feature_status_reports_effective_child_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", False)
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ASSIGNMENT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED",
        True,
    )

    status = await get_candidate_contact_status(object())  # type: ignore[arg-type]

    assert status.enabled is False
    assert status.assignment_enabled is False
    assert status.traffit_intake_enabled is False


def test_queue_and_quick_view_contract_include_non_slot_owner_states() -> None:
    assert set(_OWNER_QUEUE_STATES) == {
        "queued",
        "callback_due",
        "handoff_pending",
        "blocked_no_phone",
        "awaiting_capacity",
    }
    assert "contact_case" in CandidateQuickViewCandidate.model_fields
    assert set(_OVERSIGHT_EXCEPTION_BASE_STATES) == {
        "unassigned",
        "awaiting_capacity",
        "blocked_no_phone",
    }
    assert set(_OVERSIGHT_REASSIGNMENT_EVENTS) == {
        "reassigned",
        "cooldown_ended",
    }

    exception_sql = str(
        _oversight_exception_clause(BASE_TIME).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "handoff_pending" in exception_sql
    assert "owner_user_id IS NULL" in exception_sql
    assert "due_at <" in exception_sql
    assert "cooldown_until <=" in exception_sql
    oversight_order_sql = str(
        _oversight_priority_expression().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "handoff_pending" in oversight_order_sql
    assert "owner_user_id IS NULL" in oversight_order_sql
    assert (
        _oversight_priority_value(
            SimpleNamespace(state="handoff_pending", owner_user_id=None)
        )
        == 4
    )

    reassignment_sql = str(
        _reassignment_event_clause().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "cooldown_ended" in reassignment_sql
    assert "new_owner_user_id" in reassignment_sql
    queue_order_sql = str(
        _queue_priority_expression().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "queued" in queue_order_sql
    assert "callback_due" in queue_order_sql
    assert "handoff_pending" in queue_order_sql
    assert (
        contact_traffit_task._workflow_contact_action(
            {"workflow_state": {"type": "screening"}}
        )
        == "ensure"
    )
    for terminal_type in ("end-good", "end-bad", "wait"):
        assert (
            contact_traffit_task._workflow_contact_action(
                {"workflow_state": {"type": terminal_type}}
            )
            == "close"
        )
    assert (
        contact_traffit_task._workflow_contact_action(
            {
                "workflow_state": {
                    "type": "screening",
                    "is_rejection": True,
                }
            }
        )
        == "close"
    )
    assert contact_traffit_task._poll_sleep_seconds(300, 12.5) == pytest.approx(287.5)
    assert contact_traffit_task._poll_sleep_seconds(300, 300) == pytest.approx(1.0)
    assert contact_traffit_task._poll_sleep_seconds(300, 480) == pytest.approx(1.0)


def test_traffit_event_order_breaks_equal_second_ties_by_numeric_external_id() -> None:
    created_at = "2026-07-28 10:00:00"

    lower = contact_traffit_task._event_sort_key(
        {"id": "199", "created_at": created_at}
    )
    higher = contact_traffit_task._event_sort_key(
        {"id": "201", "created_at": created_at}
    )

    assert lower < higher


def test_traffit_page_set_collapses_identical_external_ids_once() -> None:
    raw = {
        "id": "201",
        "created_at": BASE_TIME.isoformat(),
        "employee": {"id": "candidate-1"},
        "recruitment": {"id": "job-1"},
        "workflow_state": {"type": "start"},
    }

    rows, duplicates, conflicts = contact_traffit_task._deduplicate_event_rows(
        [raw, dict(raw)]
    )

    assert rows == [raw]
    assert duplicates == 1
    assert conflicts == 0


def test_traffit_page_set_conflict_is_deterministic_and_fail_closed() -> None:
    start = {
        "id": "202",
        "created_at": BASE_TIME.isoformat(),
        "employee": {"id": "candidate-1"},
        "recruitment": {"id": "job-1"},
        "workflow_state": {"type": "start"},
    }
    terminal = {
        **start,
        "workflow_state": {"type": "end-bad"},
    }

    first, duplicates, conflicts = contact_traffit_task._deduplicate_event_rows(
        [start, terminal]
    )
    reversed_rows, reversed_duplicates, reversed_conflicts = (
        contact_traffit_task._deduplicate_event_rows([terminal, start])
    )

    assert first == reversed_rows
    assert duplicates == reversed_duplicates == 1
    assert conflicts == reversed_conflicts == 1
    assert first[0]["_candidate_contact_payload_conflict"] is True
    assert contact_traffit_task._workflow_contact_action(first[0]) is None


def test_exception_retry_queue_is_least_recently_attempted_first() -> None:
    sql = str(
        contact_traffit_task._exception_retry_statement().compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "last_attempt_at ASC NULLS FIRST" in sql
    assert sql.index("last_attempt_at ASC NULLS FIRST") < sql.index(
        "source_created_at ASC"
    )
    assert sql.index("source_created_at ASC") < sql.index(
        "candidate_contact_traffit_ledger.id ASC"
    )
    assert "LIMIT 100" in sql


async def test_non_terminal_signing_stage_opens_contact_opportunity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = MagicMock()
    db.get = AsyncMock(return_value=SimpleNamespace(pipeline_template_id=41))
    db.scalar = AsyncMock(
        return_value=SimpleNamespace(
            id=52,
            legacy_enum_value="negotiation",
        )
    )
    db.flush = AsyncMock()
    ensure = AsyncMock()
    close = AsyncMock()
    # Etap zapisuje kanoniczny command service (writer fence Priority Locka),
    # więc hook kolejki kontaktu wisi na ZWRÓCONYM wierszu, nie na własnym
    # `CandidateStage` — stąd mock `transition_process` zamiast `db.add`.
    transition = AsyncMock(
        return_value=SimpleNamespace(moved_at=BASE_TIME, candidate_id=11, job_id=22)
    )
    monkeypatch.setattr(signing_pipeline_hook, "transition_process", transition)
    monkeypatch.setattr(
        signing_pipeline_hook,
        "maybe_ensure_contact_opportunity",
        ensure,
    )
    monkeypatch.setattr(
        signing_pipeline_hook,
        "maybe_close_contact_opportunity",
        close,
    )

    await signing_pipeline_hook.move_candidate_for_signing(
        db,
        SimpleNamespace(candidate_id=11, job_id=22),
        stage_name=signing_pipeline_hook.STAGE_SENT,
        moved_by=33,
    )

    transition.assert_awaited_once()
    # Podpis nie może wykreować brakującej rekrutacji jako efektu ubocznego.
    assert transition.await_args.kwargs["require_existing"] is True
    ensure.assert_awaited_once()
    assert ensure.await_args.kwargs["occurred_at"] == BASE_TIME
    close.assert_not_awaited()


async def test_daily_traffit_equal_time_events_reach_domain_tuple_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED",
        True,
    )
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_ACTIVATION_AT",
        BASE_TIME - timedelta(days=1),
    )
    db = MagicMock()
    db.scalar = AsyncMock()
    ensured_case = object()
    closed_case = object()
    ensure = AsyncMock(return_value=ensured_case)
    close = AsyncMock(return_value=closed_case)
    monkeypatch.setattr(
        candidate_contact_service,
        "ensure_contact_opportunity",
        ensure,
    )
    monkeypatch.setattr(
        candidate_contact_service,
        "close_contact_opportunity",
        close,
    )

    ensure_result = await maybe_ensure_contact_opportunity(
        db,
        candidate_id=11,
        job_id=22,
        source="traffit",
        source_external_ref="201",
        occurred_at=BASE_TIME,
    )
    close_result = await maybe_close_contact_opportunity(
        db,
        candidate_id=11,
        job_id=22,
        source="traffit",
        source_external_ref="202",
        reason="equal_second_terminal",
        occurred_at=BASE_TIME,
    )

    assert ensure_result is ensured_case
    assert close_result is closed_case
    ensure.assert_awaited_once_with(
        db,
        candidate_id=11,
        job_id=22,
        source="traffit",
        source_external_ref="201",
        occurred_at=BASE_TIME,
        assign_if_possible=settings.CANDIDATE_CONTACT_ASSIGNMENT_ENABLED,
        # Traffit to ingress automatyczny — nigdy nie wolno mu cofnąć odmowy
        # kandydata (patrz DECLINED_CLOSE_REASONS).
        allow_declined_reopen=False,
    )
    close.assert_awaited_once_with(
        db,
        candidate_id=11,
        job_id=22,
        actor_user_id=None,
        reason="equal_second_terminal",
        occurred_at=BASE_TIME,
        source="traffit",
        source_external_ref="202",
    )
    db.scalar.assert_not_awaited()


async def test_delayed_terminal_cannot_close_newer_link_but_newer_event_can(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contact_case = SimpleNamespace(state="queued", version=7)
    opportunity = SimpleNamespace(
        closed_at=None,
        linked_at=BASE_TIME,
        source_cursor_created_at=BASE_TIME + timedelta(hours=3),
        source_cursor_external_id="200",
    )
    stale_db = MagicMock()
    stale_db.scalar = AsyncMock(
        side_effect=[object(), object(), contact_case, opportunity]
    )
    stale_db.flush = AsyncMock()

    stale_result = await close_contact_opportunity(
        stale_db,
        candidate_id=11,
        job_id=22,
        reason="lower_id_terminal",
        occurred_at=opportunity.source_cursor_created_at,
        source="traffit",
        source_external_ref="199",
    )

    assert stale_result is contact_case
    assert opportunity.closed_at is None
    assert contact_case.version == 7
    stale_db.flush.assert_not_awaited()

    audit_event = MagicMock()
    recompute = AsyncMock()
    monkeypatch.setattr(contact_coordination, "_event", audit_event)
    monkeypatch.setattr(
        contact_coordination,
        "_recompute_case_after_opportunities",
        recompute,
    )
    current_db = MagicMock()
    current_db.scalar = AsyncMock(
        side_effect=[object(), object(), contact_case, opportunity]
    )
    current_db.flush = AsyncMock()
    terminal_at = opportunity.source_cursor_created_at

    current_result = await close_contact_opportunity(
        current_db,
        candidate_id=11,
        job_id=22,
        reason="newer_terminal",
        occurred_at=terminal_at,
        source="traffit",
        source_external_ref="201",
    )

    assert current_result is contact_case
    assert opportunity.closed_at == terminal_at
    assert opportunity.closed_reason == "newer_terminal"
    assert opportunity.source_cursor_external_id == "201"
    assert opportunity.linked_at == BASE_TIME
    assert contact_case.version == 8
    assert current_db.flush.await_count == 2
    recompute.assert_awaited_once()
    audit_event.assert_called_once()


async def test_filter_rejection_does_not_advance_durable_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = f"pytest-contact-reject-{uuid.uuid4().hex}"
    previous_success = BASE_TIME - timedelta(minutes=10)
    monkeypatch.setattr(contact_traffit_task, "_STREAM", stream)
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED",
        True,
    )
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_ACTIVATION_AT",
        BASE_TIME - timedelta(days=1),
    )
    client = _RejectingTraffitClient()

    try:
        async with AsyncSessionLocal() as db:
            db.add(
                CandidateContactTraffitCursor(
                    stream=stream,
                    cursor_created_at=BASE_TIME - timedelta(minutes=5),
                    cursor_external_id="177",
                    last_success_at=previous_success,
                    status="ok",
                )
            )
            await db.commit()

            stats = await contact_traffit_task.run_traffit_contact_intake_once(
                db,
                client,  # type: ignore[arg-type]
                now=BASE_TIME,
            )
            await db.commit()
            cursor = await db.get(CandidateContactTraffitCursor, stream)
            assert cursor is not None
            assert stats.filter_rejected is True
            assert client.requests == 1
            assert cursor.cursor_created_at == BASE_TIME - timedelta(minutes=5)
            assert cursor.cursor_external_id == "177"
            assert cursor.last_success_at == previous_success
            assert cursor.status == "error"
    finally:
        async with AsyncSessionLocal() as cleanup_db:
            await cleanup_db.execute(
                delete(CandidateContactTraffitCursor).where(
                    CandidateContactTraffitCursor.stream == stream
                )
            )
            await cleanup_db.commit()


@pytest.mark.parametrize("divergent", [False, True])
async def test_same_page_external_id_dedupe_is_single_write_and_conflict_stops_cursor(
    monkeypatch: pytest.MonkeyPatch,
    divergent: bool,
) -> None:
    suffix = uuid.uuid4().hex
    stream = f"pytest-contact-page-dedupe-{suffix}"
    event_id = str(1_000_000_000_000 + (uuid.uuid4().int % 1_000_000_000))
    initial_cursor_at = BASE_TIME - timedelta(minutes=5)
    monkeypatch.setattr(contact_traffit_task, "_STREAM", stream)
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED",
        True,
    )
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_ACTIVATION_AT",
        BASE_TIME - timedelta(days=1),
    )
    first = {
        "id": event_id,
        "created_at": BASE_TIME.isoformat(),
        "employee": {"id": f"missing-candidate-{suffix}"},
        "recruitment": {"id": f"missing-job-{suffix}"},
        "workflow_state": {"type": "start"},
    }
    second = dict(first)
    if divergent:
        second["workflow_state"] = {"type": "end-bad"}

    try:
        async with AsyncSessionLocal() as db:
            db.add(
                CandidateContactTraffitCursor(
                    stream=stream,
                    cursor_created_at=initial_cursor_at,
                    cursor_external_id="0",
                    status="idle",
                )
            )
            await db.commit()
            stats = await contact_traffit_task.run_traffit_contact_intake_once(
                db,
                _StaticTraffitClient([first, second]),  # type: ignore[arg-type]
                now=BASE_TIME + timedelta(minutes=1),
            )
            await db.commit()

            cursor = await db.get(CandidateContactTraffitCursor, stream)
            ledger_rows = (
                (
                    await db.execute(
                        select(CandidateContactTraffitLedger).where(
                            CandidateContactTraffitLedger.external_event_id == event_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert cursor is not None
            assert stats.fetched == 2
            assert stats.duplicates == 1
            assert stats.exceptions == 1
            assert len(ledger_rows) == 1
            assert ledger_rows[0].attempts == 1
            if divergent:
                assert cursor.cursor_created_at == initial_cursor_at
                assert cursor.cursor_external_id == "0"
                assert (
                    ledger_rows[0].error == "conflicting_payloads_for_external_event_id"
                )
            else:
                assert cursor.cursor_created_at == BASE_TIME
                assert cursor.cursor_external_id == event_id
                assert ledger_rows[0].error is not None
                assert ledger_rows[0].error.startswith("candidate:")
    finally:
        async with AsyncSessionLocal() as cleanup_db:
            await cleanup_db.execute(
                delete(CandidateContactTraffitLedger).where(
                    CandidateContactTraffitLedger.external_event_id == event_id
                )
            )
            await cleanup_db.execute(
                delete(CandidateContactTraffitCursor).where(
                    CandidateContactTraffitCursor.stream == stream
                )
            )
            await cleanup_db.commit()


async def test_late_intake_overlap_and_daily_ingress_share_one_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid.uuid4().hex
    stream = f"pytest-contact-overlap-{suffix}"
    candidate_external_id = f"candidate-{suffix}"
    job_external_id = f"job-{suffix}"
    event_external_id = f"event-{suffix}"
    monkeypatch.setattr(contact_traffit_task, "_STREAM", stream)
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ASSIGNMENT_ENABLED", False)
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED",
        True,
    )
    monkeypatch.setattr(
        settings,
        "CANDIDATE_CONTACT_ACTIVATION_AT",
        BASE_TIME - timedelta(days=1),
    )
    raw = {
        "id": event_external_id,
        "created_at": BASE_TIME.isoformat(),
        "employee": {"id": candidate_external_id},
        "recruitment": {"id": job_external_id},
        "workflow_state": {"type": "start"},
    }
    client = _StaticTraffitClient([raw])
    candidate_id: int | None = None
    job_id: int | None = None
    client_id: int | None = None

    try:
        async with AsyncSessionLocal() as db:
            client_row = Client(
                name=f"Contact runtime {suffix}",
                status=ClientStatus.active,
            )
            db.add(client_row)
            await db.flush()
            candidate = Candidate(
                name="Runtime",
                lastname="Overlap",
                phone="+48 500 600 700",
                status=CandidateStatus.active,
                external_source="traffit",
                external_id=candidate_external_id,
            )
            job = Job(
                title=f"Runtime overlap {suffix}",
                client_id=client_row.id,
                status=JobStatus.published,
                priority=JobPriority.medium,
                external_source="traffit",
                external_id=job_external_id,
            )
            db.add_all([candidate, job])
            await db.flush()
            candidate_id = candidate.id
            job_id = job.id
            client_id = client_row.id
            await db.commit()

            late_poll_at = BASE_TIME + timedelta(hours=11)
            first = await contact_traffit_task.run_traffit_contact_intake_once(
                db,
                client,  # type: ignore[arg-type]
                now=late_poll_at,
            )
            await db.commit()
            second = await contact_traffit_task.run_traffit_contact_intake_once(
                db,
                client,  # type: ignore[arg-type]
                now=late_poll_at + timedelta(minutes=1),
            )
            await db.commit()

            # The daily importer uses the same hook after its upsert.  Its
            # later observation of the pair must extend, never duplicate, the
            # strict-poller case.
            await maybe_ensure_contact_opportunity(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                source="traffit",
                source_external_ref=f"daily-{event_external_id}",
                occurred_at=late_poll_at + timedelta(minutes=2),
            )
            await db.commit()

            assert first.processed == 1
            assert second.duplicates == 1
            assert client.requests == 2
            contact_case = await db.scalar(
                select(CandidateContactCase).where(
                    CandidateContactCase.candidate_id == candidate.id
                )
            )
            assert contact_case is not None
            assert contact_case.state == "unassigned"
            assert contact_case.queue_slot is None
            # 10:00 Warsaw source event => due at 18:00 Warsaw on that
            # business day, even though the poll only catches it after EOD.
            assert contact_case.due_at == BASE_TIME.replace(hour=16)
            assert contact_case.due_at < late_poll_at
            assert (
                await db.scalar(
                    select(func.count(CandidateContactCase.id)).where(
                        CandidateContactCase.candidate_id == candidate.id
                    )
                )
                == 1
            )
            assert (
                await db.scalar(
                    select(func.count(CandidateContactOpportunity.id)).where(
                        CandidateContactOpportunity.candidate_id == candidate.id,
                        CandidateContactOpportunity.job_id == job.id,
                    )
                )
                == 1
            )
    finally:
        async with AsyncSessionLocal() as cleanup_db:
            await cleanup_db.execute(
                delete(CandidateContactTraffitLedger).where(
                    CandidateContactTraffitLedger.external_event_id == event_external_id
                )
            )
            await cleanup_db.execute(
                delete(CandidateContactTraffitCursor).where(
                    CandidateContactTraffitCursor.stream == stream
                )
            )
            if candidate_id is not None:
                await cleanup_db.execute(
                    delete(Candidate).where(Candidate.id == candidate_id)
                )
            if job_id is not None:
                await cleanup_db.execute(delete(Job).where(Job.id == job_id))
            if client_id is not None:
                await cleanup_db.execute(delete(Client).where(Client.id == client_id))
            await cleanup_db.commit()


async def test_cancelling_one_of_two_handoffs_keeps_opportunity_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    suffix = uuid.uuid4().hex
    monkeypatch.setattr(settings, "CANDIDATE_CONTACT_ENABLED", True)
    candidate_id: int | None = None
    job_id: int | None = None
    client_id: int | None = None
    event_ids: list[int] = []

    try:
        async with AsyncSessionLocal() as db:
            client_row = Client(
                name=f"Contact calendar {suffix}",
                status=ClientStatus.active,
            )
            db.add(client_row)
            await db.flush()
            candidate = Candidate(
                name="Runtime",
                lastname="Calendar",
                status=CandidateStatus.active,
            )
            job = Job(
                title=f"Runtime calendar {suffix}",
                client_id=client_row.id,
                status=JobStatus.published,
                priority=JobPriority.medium,
            )
            db.add_all([candidate, job])
            await db.flush()
            candidate_id = candidate.id
            job_id = job.id
            client_id = client_row.id
            contact_case = await ensure_contact_opportunity(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                source="pipeline",
                occurred_at=BASE_TIME,
                assign_if_possible=False,
            )
            first_event = CalendarEvent(
                title="First screening",
                event_type=EventType.screening,
                status=EventStatus.scheduled,
                start_time=BASE_TIME + timedelta(days=1),
                candidate_id=candidate.id,
                job_id=job.id,
            )
            second_event = CalendarEvent(
                title="Second interview",
                event_type=EventType.interview,
                status=EventStatus.scheduled,
                start_time=BASE_TIME + timedelta(days=2),
                candidate_id=candidate.id,
                job_id=job.id,
            )
            db.add_all([first_event, second_event])
            await db.flush()
            event_ids.extend([first_event.id, second_event.id])

            await maybe_sync_calendar_handoff(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                event_id=first_event.id,
                scheduled=True,
                occurred_at=BASE_TIME,
            )
            await maybe_sync_calendar_handoff(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                event_id=second_event.id,
                scheduled=True,
                occurred_at=BASE_TIME,
            )
            second_event.status = EventStatus.cancelled
            await db.flush()
            await maybe_remove_calendar_handoff(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                event_id=second_event.id,
                occurred_at=BASE_TIME + timedelta(hours=1),
            )
            opportunity = await db.scalar(
                select(CandidateContactOpportunity).where(
                    CandidateContactOpportunity.case_id == contact_case.id
                )
            )
            assert opportunity is not None
            assert opportunity.meeting_event_id == first_event.id
            assert contact_case.state == "completed"

            first_event.status = EventStatus.cancelled
            await db.flush()
            await maybe_remove_calendar_handoff(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                event_id=first_event.id,
                occurred_at=BASE_TIME + timedelta(hours=2),
            )
            assert opportunity.meeting_event_id is None
            assert contact_case.state == "handoff_pending"
            await db.commit()
    finally:
        async with AsyncSessionLocal() as cleanup_db:
            if event_ids:
                await cleanup_db.execute(
                    delete(CalendarEvent).where(CalendarEvent.id.in_(event_ids))
                )
            if candidate_id is not None:
                await cleanup_db.execute(
                    delete(Candidate).where(Candidate.id == candidate_id)
                )
            if job_id is not None:
                await cleanup_db.execute(delete(Job).where(Job.id == job_id))
            if client_id is not None:
                await cleanup_db.execute(delete(Client).where(Client.id == client_id))
            await cleanup_db.commit()
