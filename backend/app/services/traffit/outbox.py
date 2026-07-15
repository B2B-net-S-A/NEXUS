"""Transactional outbox helpers for Nexus-originated Traffit changes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traffit_integration import TraffitOutboxEvent
from app.services.traffit.control import effective_control, integration_master_enabled


SUPPORTED_EVENT_TYPES = frozenset(
    {
        "candidate.create",
        "candidate.update",
        "candidate.delete_requested",
        "note.append",
        "note.correct",
        "note.delete_requested",
        "file.upload",
        "file.delete_requested",
        "assignment.add",
        "assignment.remove_requested",
        "stage.move",
        "stage.reject",
    }
)


@dataclass(frozen=True)
class OutboxCommand:
    event_type: str
    aggregate_type: str
    aggregate_id: int
    payload: Mapping[str, Any]
    candidate_id: Optional[int] = None
    entity_link_id: Optional[int] = None
    actor_user_id: Optional[int] = None
    changed_fields: tuple[str, ...] = ()
    idempotency_key: Optional[str] = None
    priority: int = 100
    max_attempts: int = 8
    origin: str = "nexus"


def event_idempotency_key(
    event_type: str,
    aggregate_type: str,
    aggregate_id: int,
    operation_id: str | uuid.UUID,
) -> str:
    return f"nexus:{aggregate_type}:{aggregate_id}:{event_type}:{operation_id}"


async def _enqueue_command(
    db: AsyncSession,
    command: OutboxCommand,
) -> Optional[TraffitOutboxEvent]:
    """Add an event to the caller's transaction without committing it.

    The function intentionally does not inspect a runtime kill-switch. Capture
    and delivery are separate concerns: paused/dry-run installations may still
    retain an auditable queue, but no worker sends it until explicitly enabled.
    Traffit-originated changes are ignored to prevent echo loops.
    """
    if command.origin == "traffit":
        return None
    if command.event_type not in SUPPORTED_EVENT_TYPES:
        raise ValueError(f"Unsupported Traffit outbox event: {command.event_type}")

    if command.idempotency_key:
        existing = await db.scalar(
            select(TraffitOutboxEvent).where(
                TraffitOutboxEvent.idempotency_key == command.idempotency_key
            )
        )
        if existing is not None:
            return existing

    # Serialize sequence allocation per candidate/aggregate inside the caller's
    # transaction. PostgreSQL advisory xact locks release automatically on
    # commit/rollback and avoid max(sequence)+1 races across API replicas.
    partition_key = (
        f"candidate:{command.candidate_id}"
        if command.candidate_id is not None
        else f"{command.aggregate_type}:{command.aggregate_id}"
    )
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:partition, 0))"),
        {"partition": partition_key},
    )
    if command.candidate_id is not None:
        partition_filter = TraffitOutboxEvent.candidate_id == command.candidate_id
    else:
        partition_filter = (
            (TraffitOutboxEvent.aggregate_type == command.aggregate_type)
            & (TraffitOutboxEvent.aggregate_id == command.aggregate_id)
        )
    current_sequence = await db.scalar(
        select(func.max(TraffitOutboxEvent.sequence)).where(partition_filter)
    )
    event_uuid = uuid.uuid4()
    event = TraffitOutboxEvent(
        event_uuid=str(event_uuid),
        aggregate_type=command.aggregate_type,
        aggregate_id=command.aggregate_id,
        candidate_id=command.candidate_id,
        entity_link_id=command.entity_link_id,
        event_type=command.event_type,
        payload=dict(command.payload),
        changed_fields=list(command.changed_fields),
        actor_user_id=command.actor_user_id,
        origin=command.origin,
        idempotency_key=command.idempotency_key or str(event_uuid),
        sequence=int(current_sequence or 0) + 1,
        priority=command.priority,
        status="pending",
        attempts=0,
        max_attempts=command.max_attempts,
    )
    db.add(event)
    await db.flush()
    return event


async def enqueue_traffit_event(
    db: AsyncSession,
    event_type: str,
    aggregate_type: str,
    aggregate_id: int,
    payload: Mapping[str, Any],
    *,
    actor_id: Optional[int] = None,
    origin: str = "nexus",
    priority: int = 100,
    candidate_id: Optional[int] = None,
    entity_link_id: Optional[int] = None,
    changed_fields: Iterable[str] = (),
    idempotency_key: Optional[str] = None,
    operation_id: Optional[str | uuid.UUID] = None,
    max_attempts: int = 8,
) -> Optional[TraffitOutboxEvent]:
    """Endpoint-friendly transactional enqueue helper.

    Fail-closed when the master switch is off.  When the DB control is in
    dry-run mode events are still captured even though outbound delivery is
    disabled, enabling the planned production shadow period.
    """
    if origin == "traffit":
        return None
    # Existing mutation endpoints must remain independent of the new tables
    # until the migration is deployed and the integration is explicitly armed.
    if not integration_master_enabled():
        return None
    control = await effective_control(db)
    if not control.master_enabled:
        return None
    if not control.outbound_enabled and not control.dry_run:
        return None
    key = idempotency_key
    if key is None and operation_id is not None:
        key = event_idempotency_key(
            event_type, aggregate_type, aggregate_id, operation_id
        )
    return await _enqueue_command(
        db,
        OutboxCommand(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            candidate_id=candidate_id,
            entity_link_id=entity_link_id,
            actor_user_id=actor_id,
            changed_fields=tuple(changed_fields),
            idempotency_key=key,
            priority=priority,
            max_attempts=max_attempts,
            origin=origin,
        ),
    )


async def enqueue_candidate_changes(
    db: AsyncSession,
    *,
    candidate_id: int,
    payload: Mapping[str, Any],
    changed_fields: Iterable[str],
    actor_user_id: Optional[int],
    entity_link_id: Optional[int] = None,
    operation_id: Optional[str | uuid.UUID] = None,
) -> TraffitOutboxEvent:
    """Convenience helper used by candidate mutation endpoints."""
    event_type = "candidate.update" if entity_link_id is not None else "candidate.create"
    op_id = operation_id or uuid.uuid4()
    event = await _enqueue_command(
        db,
        OutboxCommand(
            event_type=event_type,
            aggregate_type="candidate",
            aggregate_id=candidate_id,
            candidate_id=candidate_id,
            entity_link_id=entity_link_id,
            actor_user_id=actor_user_id,
            payload=payload,
            changed_fields=tuple(changed_fields),
            idempotency_key=event_idempotency_key(
                event_type, "candidate", candidate_id, op_id
            ),
        ),
    )
    assert event is not None
    return event
