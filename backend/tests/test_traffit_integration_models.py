"""Metadata-level tests for bidirectional Traffit persistence primitives.

No DB required — asserts the SQLAlchemy metadata (tables, unique guards) that
plan PR2 promises. The DB-level behaviour is covered by `alembic upgrade heads`
+ import smoke in hosted CI. Zostały powiązania encji i skrzynka webhooków;
modele siedmiu tabel synchronizacji dwukierunkowej zdjęto 15.11.2026.
"""

from app.core.database import Base
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.note import Note
from app.models.pipeline_template import RejectionReason
from app.models.traffit_integration import TraffitEntityLink, TraffitWebhookEvent
from app.models.traffit_sync_state import TraffitSyncState


def _index(table, name: str):
    return next(index for index in table.indexes if index.name == name)


def test_all_traffit_persistence_tables_are_registered() -> None:
    expected = {
        TraffitEntityLink.__tablename__,
        TraffitWebhookEvent.__tablename__,
    }
    assert expected <= set(Base.metadata.tables)


def test_durable_queues_and_links_have_database_dedupe_guards() -> None:
    local_link = _index(TraffitEntityLink.__table__, "ux_traffit_entity_links_nexus")
    remote_link = _index(TraffitEntityLink.__table__, "ux_traffit_entity_links_remote")
    assert local_link.unique and remote_link.unique
    assert local_link.dialect_options["postgresql"]["where"] is not None
    assert remote_link.dialect_options["postgresql"]["where"] is not None

    webhook_unique = {
        tuple(column.name for column in constraint.columns)
        for constraint in TraffitWebhookEvent.__table__.constraints
        if getattr(constraint, "name", None) == "uq_traffit_webhook_dedupe"
    }
    assert webhook_unique == {("subscription_id", "dedupe_key")}


def test_entity_link_keeps_schema_hash_for_base_snapshot() -> None:
    # Zmiana kontraktu pól tenanta unieważnia bazę 3-way merge — bez hasha
    # schematu merge porównywałby nieporównywalne projekcje.
    assert "base_schema_hash" in TraffitEntityLink.__table__.c.keys()


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


def test_migration_and_entrypoint_mirror_stay_in_sync() -> None:
    # Repozytoryjna pułapka prod: alembic bywa multi-head → wszystko, co musi
    # wylądować na prod, MUSI mieć idempotentny mirror w entrypoint.sh.
    # Ten test pilnuje, żeby ktoś nie dodał tabeli/kolumny tylko w migracji.
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    migration = (
        backend_dir
        / "alembic"
        / "versions"
        / "0173_traffit_bidirectional_persistence.py"
    ).read_text()
    entrypoint = (backend_dir / "entrypoint.sh").read_text()

    for table in ("traffit_entity_links", "traffit_webhook_events"):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in migration, table
        assert f"CREATE TABLE IF NOT EXISTS {table}" in entrypoint, table

    for column_stmt in (
        "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS profile_about",
        "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS custom_fields",
        "ALTER TABLE notes ADD COLUMN IF NOT EXISTS external_id",
        "ALTER TABLE notes ADD COLUMN IF NOT EXISTS supersedes_note_id",
        "ALTER TABLE rejection_reasons ADD COLUMN IF NOT EXISTS",
    ):
        assert column_stmt in migration, column_stmt
        assert column_stmt in entrypoint, column_stmt
