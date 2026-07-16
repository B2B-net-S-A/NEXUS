"""Durable state for the bidirectional Traffit integration.

The integration deliberately keeps lifecycle values in ``VARCHAR`` columns
instead of PostgreSQL enums.  Integration workers evolve independently from
the core ATS domain and must be able to introduce a new retry/dead-letter
state without a blocking enum migration.

The tables in this module are transport-agnostic persistence primitives:

* entity links keep the three-way-merge baseline and source identities,
* outbox/inbox rows make delivery durable and idempotent,
* conflicts preserve both values until an administrator resolves them,
* sync runs/cursors and leases make polling restart-safe and single-leader,
* runtime control is an additional soft gate below environment kill-switches.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


def _uuid_string() -> str:
    return str(uuid4())


class TraffitEntityLink(Base, TimestampMixin):
    """Stable Nexus↔Traffit identity and three-way-merge baseline."""

    __tablename__ = "traffit_entity_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    nexus_entity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    traffit_entity_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )

    # active | pending | conflict | error | manual_action_required | detached
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="active", server_default="active"
    )
    base_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    # Hash kontraktu pól, z którym zbudowano base_snapshot — zmiana schematu
    # tenanta unieważnia bazę do 3-way merge zamiast cicho porównywać
    # nieporównywalne projekcje.
    base_schema_hash: Mapped[Optional[str]] = mapped_column(String(64))
    nexus_snapshot_hash: Mapped[Optional[str]] = mapped_column(String(64))
    traffit_snapshot_hash: Mapped[Optional[str]] = mapped_column(String(64))

    nexus_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    traffit_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    missing_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    missing_strikes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    source_deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    pending_delete_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    last_direction: Mapped[Optional[str]] = mapped_column(String(20))
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index(
            "ux_traffit_entity_links_nexus",
            "entity_type",
            "nexus_entity_id",
            unique=True,
            postgresql_where=text("nexus_entity_id IS NOT NULL"),
        ),
        Index(
            "ux_traffit_entity_links_remote",
            "entity_type",
            "traffit_entity_id",
            unique=True,
            postgresql_where=text("traffit_entity_id IS NOT NULL"),
        ),
        Index(
            "ix_traffit_entity_links_candidate_status",
            "candidate_id",
            "status",
        ),
        Index("ix_traffit_entity_links_last_seen", "entity_type", "last_seen_at"),
    )


class TraffitFieldContract(Base, TimestampMixin):
    """Tenant-specific metadata contract for one Traffit field/capability."""

    __tablename__ = "traffit_field_contracts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    field_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # create | patch | read
    capability: Mapped[str] = mapped_column(String(20), nullable=False)
    endpoint: Mapped[Optional[str]] = mapped_column(String(255))
    local_path: Mapped[Optional[str]] = mapped_column(String(255))
    data_type: Mapped[Optional[str]] = mapped_column(String(100))
    adapter: Mapped[Optional[str]] = mapped_column(String(100))
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    readable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    writable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    choices: Mapped[Optional[list[Any]]] = mapped_column(JSONB)
    raw_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    schema_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # active | read_only | quarantined | removed
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )
    quarantine_reason: Mapped[Optional[str]] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "field_name", "capability", name="uq_traffit_field_contract_capability"
        ),
        Index("ix_traffit_field_contracts_status", "status"),
    )


class TraffitOutboxEvent(Base, TimestampMixin):
    """Transactional outbox row for a Nexus-originated mutation."""

    __tablename__ = "traffit_outbox_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_uuid: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True, default=_uuid_string
    )
    aggregate_type: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregate_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    entity_link_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("traffit_entity_links.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    changed_fields: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    origin: Mapped[str] = mapped_column(
        String(20), nullable=False, default="nexus", server_default="nexus"
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    sequence: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, server_default="100"
    )

    # pending | processing | retry | succeeded | dry_run | dead_letter | cancelled
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=8, server_default="8"
    )
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now()
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[Optional[str]] = mapped_column(String(255))
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    remote_response: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index(
            "ix_traffit_outbox_due",
            "priority",
            "next_attempt_at",
            "id",
            postgresql_where=text("status IN ('pending', 'retry')"),
        ),
        Index(
            "ix_traffit_outbox_aggregate_order",
            "aggregate_type",
            "aggregate_id",
            "sequence",
            "id",
        ),
        Index("ix_traffit_outbox_candidate_status", "candidate_id", "status"),
    )


class TraffitWebhookEvent(Base, TimestampMixin):
    """Durable, deduplicated inbox row for a Traffit webhook signal."""

    __tablename__ = "traffit_webhook_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subscription_id: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    remote_entity_type: Mapped[Optional[str]] = mapped_column(String(50))
    remote_entity_id: Mapped[Optional[str]] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # pending | processing | retry | succeeded | dead_letter | ignored
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=8, server_default="8"
    )
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now()
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[Optional[str]] = mapped_column(String(255))
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "dedupe_key", name="uq_traffit_webhook_dedupe"
        ),
        Index(
            "ix_traffit_webhook_due",
            "next_attempt_at",
            "id",
            postgresql_where=text("status IN ('pending', 'retry')"),
        ),
        Index(
            "ix_traffit_webhook_remote_entity",
            "remote_entity_type",
            "remote_entity_id",
        ),
    )


class TraffitSyncConflict(Base, TimestampMixin):
    """A same-field/stage divergence that requires an explicit decision."""

    __tablename__ = "traffit_sync_conflicts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_link_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("traffit_entity_links.id", ondelete="SET NULL"), nullable=True
    )
    outbox_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("traffit_outbox_events.id", ondelete="SET NULL"), nullable=True
    )
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    nexus_entity_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    traffit_entity_id: Mapped[Optional[str]] = mapped_column(String(255))
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    field_path: Mapped[Optional[str]] = mapped_column(String(255))
    conflict_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Retry tego samego requestu (np. DELETE kandydata) trafia w unikalny klucz
    # i dostaje istniejącą sprawę — jeden request = jeden rekord = jedno ID.
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    base_value: Mapped[Optional[Any]] = mapped_column(JSONB)
    nexus_value: Mapped[Optional[Any]] = mapped_column(JSONB)
    traffit_value: Mapped[Optional[Any]] = mapped_column(JSONB)

    # open | resolved | ignored | manual_action_required
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="open", server_default="open"
    )
    # nexus | traffit | merged | manual | detach | ignored
    resolution: Mapped[Optional[str]] = mapped_column(String(30))
    resolved_value: Mapped[Optional[Any]] = mapped_column(JSONB)
    resolution_note: Mapped[Optional[str]] = mapped_column(Text)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        Index(
            "ix_traffit_conflicts_open",
            "detected_at",
            "id",
            postgresql_where=text("status IN ('open', 'manual_action_required')"),
        ),
        Index("ix_traffit_conflicts_candidate", "candidate_id", "status"),
        Index(
            "ix_traffit_conflicts_entity",
            "entity_type",
            "nexus_entity_id",
            "traffit_entity_id",
        ),
        Index(
            "ux_traffit_conflicts_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class TraffitSyncRun(Base, TimestampMixin):
    """Top-level audit row for a poll, baseline or reconcile execution."""

    __tablename__ = "traffit_sync_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_uuid: Mapped[str] = mapped_column(
        String(36), nullable=False, unique=True, default=_uuid_string
    )
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # queued | running | succeeded | partial | failed | cancelled
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", server_default="queued"
    )
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    leader_id: Mapped[Optional[str]] = mapped_column(String(255))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cursor_before: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    cursor_after: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    errors: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )

    __table_args__ = (
        Index("ix_traffit_sync_runs_status_started", "status", "started_at"),
        Index("ix_traffit_sync_runs_mode_created", "mode", "created_at"),
    )


class TraffitSyncRunPhase(Base, TimestampMixin):
    """Per-stream progress; a cursor is committed only for complete phases."""

    __tablename__ = "traffit_sync_run_phases"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("traffit_sync_runs.id", ondelete="CASCADE"), nullable=False
    )
    phase: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", server_default="queued"
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cursor_before: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    cursor_after: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    pages_processed: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    items_seen: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    items_applied: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    items_skipped: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    conflicts_created: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("run_id", "phase", name="uq_traffit_sync_run_phase"),
        Index("ix_traffit_sync_run_phases_run_status", "run_id", "status"),
    )


class IntegrationLease(Base, TimestampMixin):
    """Database-backed single-leader lease shared by all backend replicas."""

    __tablename__ = "integration_leases"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    holder_id: Mapped[str] = mapped_column(String(255), nullable=False)
    acquired_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    generation: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, server_default="1"
    )
    lease_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


class TraffitIntegrationControl(Base, TimestampMixin):
    """Runtime soft switches; environment flags remain the hard upper bound."""

    __tablename__ = "traffit_integration_control"

    integration: Mapped[str] = mapped_column(
        String(50), primary_key=True, default="traffit", server_default="traffit"
    )
    webhook_accept_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    inbound_apply_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    poll_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    outbound_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    paused_reason: Mapped[Optional[str]] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
