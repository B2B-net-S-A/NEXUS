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
from sqlalchemy import delete, select
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
    CandidateContactOpportunity,
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


# ── Regresje P2: zamrożony kursor, obserwowalność i higiena RODO ─────────────
