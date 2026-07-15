"""Metadata-level tests for bidirectional Traffit persistence primitives."""

from app.core.database import Base
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.note import Note
from app.models.pipeline_template import RejectionReason
from app.models.traffit_integration import (
    IntegrationLease,
    TraffitEntityLink,
    TraffitFieldContract,
    TraffitIntegrationControl,
    TraffitOutboxEvent,
    TraffitSyncConflict,
    TraffitSyncRun,
    TraffitSyncRunPhase,
    TraffitWebhookEvent,
)
from app.models.traffit_sync_state import TraffitSyncState


def _index(table, name: str):
    return next(index for index in table.indexes if index.name == name)


def test_all_traffit_persistence_tables_are_registered() -> None:
    expected = {
        TraffitEntityLink.__tablename__,
        TraffitFieldContract.__tablename__,
        TraffitOutboxEvent.__tablename__,
        TraffitWebhookEvent.__tablename__,
        TraffitSyncConflict.__tablename__,
        TraffitSyncRun.__tablename__,
        TraffitSyncRunPhase.__tablename__,
        IntegrationLease.__tablename__,
        TraffitIntegrationControl.__tablename__,
    }
    assert expected <= set(Base.metadata.tables)


def test_durable_queues_and_links_have_database_dedupe_guards() -> None:
    local_link = _index(TraffitEntityLink.__table__, "ux_traffit_entity_links_nexus")
    remote_link = _index(TraffitEntityLink.__table__, "ux_traffit_entity_links_remote")
    assert local_link.unique and remote_link.unique
    assert local_link.dialect_options["postgresql"]["where"] is not None
    assert remote_link.dialect_options["postgresql"]["where"] is not None

    assert TraffitOutboxEvent.__table__.c.idempotency_key.unique
    webhook_unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in TraffitWebhookEvent.__table__.constraints
        if getattr(constraint, "name", None) == "uq_traffit_webhook_dedupe"
    }
    assert webhook_unique == {("subscription_id", "dedupe_key")}


def test_runtime_control_defaults_fail_closed_except_dry_run() -> None:
    columns = TraffitIntegrationControl.__table__.c
    assert str(columns.webhook_accept_enabled.server_default.arg) == "false"
    assert str(columns.inbound_apply_enabled.server_default.arg) == "false"
    assert str(columns.poll_enabled.server_default.arg) == "false"
    assert str(columns.outbound_enabled.server_default.arg) == "false"
    assert str(columns.dry_run.server_default.arg) == "true"


def test_core_models_expose_bidirectional_sync_state() -> None:
    assert {"profile_about", "custom_fields"} <= set(Candidate.__table__.c.keys())
    assert {
        "external_source",
        "external_id",
        "source_created_at",
        "source_updated_at",
        "source_deleted_at",
        "supersedes_note_id",
    } <= set(Note.__table__.c.keys())
    assert {
        "content_sha256",
        "source_manifest_fingerprint",
        "source_deleted_at",
    } <= set(CandidateDocument.__table__.c.keys())
    assert {"external_source", "external_id"} <= set(RejectionReason.__table__.c.keys())
    assert {
        "cursor_at",
        "cursor_external_id",
        "cursor_payload",
        "last_attempt_at",
        "last_success_at",
        "consecutive_failures",
        "last_error",
        "next_due_at",
    } <= set(TraffitSyncState.__table__.c.keys())
