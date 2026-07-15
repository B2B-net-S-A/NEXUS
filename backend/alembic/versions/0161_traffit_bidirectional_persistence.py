"""Durable persistence for bidirectional Traffit integration.

Revision ID: 0161_traffit_bidirectional_persistence
Revises: 0160_contract_document_type_order
Create Date: 2026-07-14

Adds the transactional outbox, durable webhook inbox, three-way merge ledger,
conflict audit, run history, database lease and runtime control required by the
Nexus↔Traffit integration. Existing one-way import identities are backfilled
without deleting or rewriting their legacy source fields.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0161_traffit_bidirectional_persistence"
down_revision = "0160_contract_document_type_order"
branch_labels = None
depends_on = None


JSON_EMPTY_OBJECT = sa.text("'{}'::jsonb")
JSON_EMPTY_ARRAY = sa.text("'[]'::jsonb")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def upgrade() -> None:
    # Core entity extensions. Defaults keep all existing insert paths working
    # while the integration is safely disabled by default.
    op.add_column("candidates", sa.Column("profile_about", sa.Text(), nullable=True))
    op.add_column(
        "candidates",
        sa.Column(
            "custom_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=JSON_EMPTY_OBJECT,
        ),
    )

    op.add_column("notes", sa.Column("external_source", sa.String(50)))
    op.add_column("notes", sa.Column("external_id", sa.String(255)))
    op.add_column("notes", sa.Column("source_created_at", sa.DateTime(timezone=True)))
    op.add_column("notes", sa.Column("source_updated_at", sa.DateTime(timezone=True)))
    op.add_column("notes", sa.Column("source_deleted_at", sa.DateTime(timezone=True)))
    op.add_column("notes", sa.Column("supersedes_note_id", sa.Integer()))
    op.create_foreign_key(
        "fk_notes_supersedes_note_id_notes",
        "notes",
        "notes",
        ["supersedes_note_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("candidate_documents", sa.Column("content_sha256", sa.String(64)))
    op.add_column(
        "candidate_documents",
        sa.Column("source_manifest_fingerprint", sa.String(64)),
    )
    op.add_column(
        "candidate_documents",
        sa.Column("source_deleted_at", sa.DateTime(timezone=True)),
    )

    op.add_column("rejection_reasons", sa.Column("external_source", sa.String(50)))
    op.add_column("rejection_reasons", sa.Column("external_id", sa.String(100)))
    op.execute(
        sa.text(
            "UPDATE rejection_reasons SET external_source = 'manual' "
            "WHERE external_source IS NULL"
        )
    )
    op.create_index(
        "ix_rejection_reasons_external_source",
        "rejection_reasons",
        ["external_source"],
    )
    op.create_index(
        "ix_rejection_reasons_external_id",
        "rejection_reasons",
        ["external_id"],
    )
    op.create_index(
        "ux_rejection_reasons_external_source_id",
        "rejection_reasons",
        ["external_source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )

    op.add_column(
        "traffit_sync_state", sa.Column("cursor_at", sa.DateTime(timezone=True))
    )
    op.add_column("traffit_sync_state", sa.Column("cursor_external_id", sa.String(255)))
    op.add_column(
        "traffit_sync_state",
        sa.Column("cursor_payload", postgresql.JSONB(astext_type=sa.Text())),
    )
    op.add_column(
        "traffit_sync_state",
        sa.Column("last_attempt_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "traffit_sync_state",
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "traffit_sync_state",
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column("traffit_sync_state", sa.Column("last_error", sa.Text()))
    op.add_column(
        "traffit_sync_state", sa.Column("next_due_at", sa.DateTime(timezone=True))
    )

    op.create_table(
        "traffit_entity_links",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("nexus_entity_id", sa.BigInteger()),
        sa.Column("traffit_entity_id", sa.String(255)),
        sa.Column("candidate_id", sa.Integer()),
        sa.Column("status", sa.String(40), nullable=False, server_default="active"),
        sa.Column("base_snapshot", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("nexus_snapshot_hash", sa.String(64)),
        sa.Column("traffit_snapshot_hash", sa.String(64)),
        sa.Column("shared_snapshot_hash", sa.String(64)),
        sa.Column("nexus_updated_at", sa.DateTime(timezone=True)),
        sa.Column("traffit_updated_at", sa.DateTime(timezone=True)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("missing_since", sa.DateTime(timezone=True)),
        sa.Column("missing_strikes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_deleted_at", sa.DateTime(timezone=True)),
        sa.Column("pending_delete_at", sa.DateTime(timezone=True)),
        sa.Column("last_direction", sa.String(20)),
        sa.Column("last_error", sa.Text()),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidates.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_traffit_entity_links_nexus",
        "traffit_entity_links",
        ["entity_type", "nexus_entity_id"],
        unique=True,
        postgresql_where=sa.text("nexus_entity_id IS NOT NULL"),
    )
    op.create_index(
        "ux_traffit_entity_links_remote",
        "traffit_entity_links",
        ["entity_type", "traffit_entity_id"],
        unique=True,
        postgresql_where=sa.text("traffit_entity_id IS NOT NULL"),
    )
    op.create_index(
        "ix_traffit_entity_links_candidate_status",
        "traffit_entity_links",
        ["candidate_id", "status"],
    )
    op.create_index(
        "ix_traffit_entity_links_last_seen",
        "traffit_entity_links",
        ["entity_type", "last_seen_at"],
    )

    op.create_table(
        "traffit_field_contracts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("field_name", sa.String(255), nullable=False),
        sa.Column("capability", sa.String(20), nullable=False),
        sa.Column("endpoint", sa.String(255)),
        sa.Column("local_path", sa.String(255)),
        sa.Column("data_type", sa.String(100)),
        sa.Column("adapter", sa.String(100)),
        sa.Column("required", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("readable", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("writable", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("choices", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("raw_metadata", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("schema_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="active"),
        sa.Column("quarantine_reason", sa.Text()),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "field_name",
            "capability",
            name="uq_traffit_field_contract_capability",
        ),
    )
    op.create_index(
        "ix_traffit_field_contracts_status",
        "traffit_field_contracts",
        ["status"],
    )

    op.create_table(
        "traffit_outbox_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_uuid", sa.String(36), nullable=False),
        sa.Column("aggregate_type", sa.String(50), nullable=False),
        sa.Column("aggregate_id", sa.BigInteger(), nullable=False),
        sa.Column("candidate_id", sa.Integer()),
        sa.Column("entity_link_id", sa.BigInteger()),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=JSON_EMPTY_OBJECT,
        ),
        sa.Column(
            "changed_fields",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=JSON_EMPTY_ARRAY,
        ),
        sa.Column("actor_user_id", sa.Integer()),
        sa.Column("origin", sa.String(20), nullable=False, server_default="nexus"),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(255)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("remote_response", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("last_error", sa.Text()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidates.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["entity_link_id"], ["traffit_entity_links.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_uuid", name="uq_traffit_outbox_event_uuid"),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_traffit_outbox_idempotency_key"
        ),
    )
    op.create_index(
        "ix_traffit_outbox_due",
        "traffit_outbox_events",
        ["priority", "next_attempt_at", "id"],
        postgresql_where=sa.text("status IN ('pending', 'retry')"),
    )
    op.create_index(
        "ix_traffit_outbox_aggregate_order",
        "traffit_outbox_events",
        ["aggregate_type", "aggregate_id", "sequence", "id"],
    )
    op.create_index(
        "ix_traffit_outbox_candidate_status",
        "traffit_outbox_events",
        ["candidate_id", "status"],
    )

    op.create_table(
        "traffit_webhook_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("subscription_id", sa.String(100), nullable=False),
        sa.Column("dedupe_key", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("remote_entity_type", sa.String(50)),
        sa.Column("remote_entity_id", sa.String(255)),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=JSON_EMPTY_OBJECT,
        ),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.String(255)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subscription_id", "dedupe_key", name="uq_traffit_webhook_dedupe"
        ),
    )
    op.create_index(
        "ix_traffit_webhook_due",
        "traffit_webhook_events",
        ["next_attempt_at", "id"],
        postgresql_where=sa.text("status IN ('pending', 'retry')"),
    )
    op.create_index(
        "ix_traffit_webhook_remote_entity",
        "traffit_webhook_events",
        ["remote_entity_type", "remote_entity_id"],
    )

    op.create_table(
        "traffit_sync_conflicts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("entity_link_id", sa.BigInteger()),
        sa.Column("outbox_event_id", sa.BigInteger()),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("nexus_entity_id", sa.BigInteger()),
        sa.Column("traffit_entity_id", sa.String(255)),
        sa.Column("candidate_id", sa.Integer()),
        sa.Column("field_path", sa.String(255)),
        sa.Column("conflict_type", sa.String(50), nullable=False),
        sa.Column("base_value", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("nexus_value", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("traffit_value", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("status", sa.String(30), nullable=False, server_default="open"),
        sa.Column("resolution", sa.String(30)),
        sa.Column("resolved_value", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("resolution_note", sa.Text()),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.Integer()),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["candidates.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["entity_link_id"], ["traffit_entity_links.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["outbox_event_id"], ["traffit_outbox_events.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_traffit_conflicts_open",
        "traffit_sync_conflicts",
        ["detected_at", "id"],
        postgresql_where=sa.text("status IN ('open', 'manual_action_required')"),
    )
    op.create_index(
        "ix_traffit_conflicts_candidate",
        "traffit_sync_conflicts",
        ["candidate_id", "status"],
    )
    op.create_index(
        "ix_traffit_conflicts_entity",
        "traffit_sync_conflicts",
        ["entity_type", "nexus_entity_id", "traffit_entity_id"],
    )

    op.create_table(
        "traffit_sync_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_uuid", sa.String(36), nullable=False),
        sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("trigger", sa.String(30), nullable=False),
        sa.Column(
            "scope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=JSON_EMPTY_OBJECT,
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("leader_id", sa.String(255)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("cursor_before", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("cursor_after", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=JSON_EMPTY_OBJECT,
        ),
        sa.Column(
            "errors",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=JSON_EMPTY_ARRAY,
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_uuid", name="uq_traffit_sync_runs_uuid"),
    )
    op.create_index(
        "ix_traffit_sync_runs_status_started",
        "traffit_sync_runs",
        ["status", "started_at"],
    )
    op.create_index(
        "ix_traffit_sync_runs_mode_created",
        "traffit_sync_runs",
        ["mode", "created_at"],
    )

    op.create_table(
        "traffit_sync_run_phases",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.BigInteger(), nullable=False),
        sa.Column("phase", sa.String(100), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="queued"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("cursor_before", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("cursor_after", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("pages_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_applied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("items_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "conflicts_created", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("complete", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "stats",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=JSON_EMPTY_OBJECT,
        ),
        sa.Column("error", sa.Text()),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["run_id"], ["traffit_sync_runs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "phase", name="uq_traffit_sync_run_phase"),
    )
    op.create_index(
        "ix_traffit_sync_run_phases_run_status",
        "traffit_sync_run_phases",
        ["run_id", "status"],
    )

    op.create_table(
        "integration_leases",
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("holder_id", sa.String(255), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=JSON_EMPTY_OBJECT,
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_index(
        "ix_integration_leases_expires_at",
        "integration_leases",
        ["expires_at"],
    )

    op.create_table(
        "traffit_integration_control",
        sa.Column(
            "integration", sa.String(50), nullable=False, server_default="traffit"
        ),
        sa.Column(
            "webhook_accept_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column(
            "inbound_apply_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("poll_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "outbound_enabled", sa.Boolean(), nullable=False, server_default="false"
        ),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("paused_reason", sa.Text()),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=JSON_EMPTY_OBJECT,
        ),
        sa.Column("updated_by", sa.Integer()),
        *_timestamps(),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("integration"),
    )

    # Legacy custom fields were mixed into cv_extracted_data. Copy only keys
    # owned by Traffit and leave the original document untouched for rollback.
    op.execute(
        sa.text(
            """
            UPDATE candidates AS c
               SET custom_fields = COALESCE(
                   (
                       SELECT jsonb_object_agg(e.key, e.value)
                         FROM jsonb_each(c.cv_extracted_data) AS e
                        WHERE left(e.key, 7) = 'traffit'
                   ),
                   '{}'::jsonb
               )
             WHERE jsonb_typeof(c.cv_extracted_data) = 'object'
               AND EXISTS (
                   SELECT 1
                     FROM jsonb_each(c.cv_extracted_data) AS e
                    WHERE left(e.key, 7) = 'traffit'
               )
            """
        )
    )
    # Existing Traffit candidate_about was historically stored in ai_summary.
    # Copy it once so future AI summaries can evolve independently.
    op.execute(
        sa.text(
            """
            UPDATE candidates
               SET profile_about = ai_summary
             WHERE external_source = 'traffit'
               AND profile_about IS NULL
               AND ai_summary IS NOT NULL
            """
        )
    )

    # Promote structured note identities from the already-stamped source_ref.
    # If historical duplicates exist, only the oldest row receives external_id
    # so creation of the partial unique index remains safe and deterministic.
    op.execute(
        sa.text(
            """
            UPDATE notes
               SET external_source = 'traffit',
                   source_created_at = COALESCE(source_created_at, created_at),
                   source_updated_at = COALESCE(source_updated_at, updated_at)
             WHERE source_ref LIKE 'traffit:activity:%'
            """
        )
    )
    op.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT id,
                       substring(source_ref FROM length('traffit:activity:') + 1)
                           AS remote_id,
                       row_number() OVER (
                           PARTITION BY substring(
                               source_ref FROM length('traffit:activity:') + 1
                           )
                           ORDER BY id
                       ) AS rn
                  FROM notes
                 WHERE source_ref LIKE 'traffit:activity:%'
                   AND length(source_ref) > length('traffit:activity:')
            )
            UPDATE notes AS n
               SET external_id = r.remote_id
              FROM ranked AS r
             WHERE n.id = r.id
               AND r.rn = 1
            """
        )
    )
    op.create_index("ix_notes_external_source", "notes", ["external_source"])
    op.create_index("ix_notes_external_id", "notes", ["external_id"])
    op.create_index(
        "ux_notes_external_source_id",
        "notes",
        ["external_source", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index(
        "ix_notes_candidate_source_created",
        "notes",
        ["candidate_id", "external_source", "source_created_at"],
    )
    op.create_index(
        "ux_candidate_documents_candidate_sha",
        "candidate_documents",
        ["candidate_id", "content_sha256"],
        unique=True,
        postgresql_where=sa.text(
            "content_sha256 IS NOT NULL AND source_deleted_at IS NULL"
        ),
    )
    op.create_index(
        "ix_candidate_documents_manifest",
        "candidate_documents",
        ["candidate_id", "source_manifest_fingerprint"],
    )

    # Upgrade legacy phase watermarks into per-stream cursors. A failed legacy
    # run is not marked successful and therefore remains due for retry.
    op.execute(
        sa.text(
            """
            UPDATE traffit_sync_state
               SET cursor_at = last_synced_at,
                   cursor_external_id = last_max_external_id::text,
                   last_attempt_at = last_run_started_at,
                   last_success_at = CASE
                       WHEN last_status = 'ok' THEN last_run_finished_at
                       ELSE NULL
                   END,
                   consecutive_failures = CASE
                       WHEN last_status IN ('error', 'errors') THEN 1
                       ELSE 0
                   END,
                   last_error = CASE
                       WHEN last_status IN ('error', 'errors')
                       THEN LEFT(COALESCE(stats ->> 'error', stats::text), 10000)
                       ELSE NULL
                   END
            """
        )
    )

    # Backfill stable links from every existing Traffit identity in core scope.
    op.execute(
        sa.text(
            """
            INSERT INTO traffit_entity_links (
                entity_type, nexus_entity_id, traffit_entity_id, candidate_id,
                status, base_snapshot, nexus_updated_at, last_synced_at,
                last_seen_at, created_at, updated_at
            )
            SELECT 'candidate', c.id, c.external_id, c.id, 'active',
                   jsonb_build_object(
                       'name', c.name,
                       'lastname', c.lastname,
                       'email', c.email,
                       'phone', c.phone,
                       'location', c.location,
                       'linkedin', c.linkedin,
                       'profile_about', c.profile_about,
                       'status', c.status::text,
                       'source', c.source,
                       'languages', COALESCE(c.languages, '[]'::jsonb),
                       'custom_fields', c.custom_fields
                   ),
                   c.updated_at, now(), now(), now(), now()
              FROM candidates AS c
             WHERE c.external_source = 'traffit'
               AND c.external_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
    )
    for entity_type, table_name in (
        ("job", "jobs"),
        ("stage", "candidate_stages"),
        ("workflow", "pipeline_templates"),
        ("stage_definition", "pipeline_stage_defs"),
    ):
        op.execute(
            sa.text(
                f"""
                INSERT INTO traffit_entity_links (
                    entity_type, nexus_entity_id, traffit_entity_id, status,
                    base_snapshot, nexus_updated_at, last_synced_at,
                    last_seen_at, created_at, updated_at
                )
                SELECT :entity_type, t.id, t.external_id, 'active',
                       jsonb_build_object('external_id', t.external_id),
                       t.updated_at, now(), now(), now(), now()
                  FROM {table_name} AS t
                 WHERE t.external_source = 'traffit'
                   AND t.external_id IS NOT NULL
                ON CONFLICT DO NOTHING
                """
            ).bindparams(entity_type=entity_type)
        )
    op.execute(
        sa.text(
            """
            INSERT INTO traffit_entity_links (
                entity_type, nexus_entity_id, traffit_entity_id, candidate_id,
                status, base_snapshot, nexus_updated_at, last_synced_at,
                last_seen_at, created_at, updated_at
            )
            SELECT 'note', n.id, n.external_id, n.candidate_id, 'active',
                   jsonb_build_object('content', n.content, 'type', n.note_type::text),
                   n.updated_at, now(), now(), now(), now()
              FROM notes AS n
             WHERE n.external_source = 'traffit'
               AND n.external_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO traffit_entity_links (
                entity_type, nexus_entity_id, traffit_entity_id, candidate_id,
                status, base_snapshot, nexus_updated_at, last_synced_at,
                last_seen_at, created_at, updated_at
            )
            SELECT 'file', d.id, d.external_id, d.candidate_id, 'active',
                   jsonb_build_object(
                       'filename', d.filename,
                       'size_bytes', d.size_bytes,
                       'content_type', d.content_type
                   ),
                   d.updated_at, now(), now(), now(), now()
              FROM candidate_documents AS d
             WHERE d.external_source = 'traffit'
               AND d.external_id IS NOT NULL
            ON CONFLICT DO NOTHING
            """
        )
    )

    op.execute(
        sa.text(
            """
            INSERT INTO traffit_integration_control (
                integration, webhook_accept_enabled, inbound_apply_enabled,
                poll_enabled, outbound_enabled, dry_run, settings,
                created_at, updated_at
            ) VALUES (
                'traffit', false, false, false, false, true, '{}'::jsonb,
                now(), now()
            )
            ON CONFLICT (integration) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table("traffit_sync_conflicts")
    op.drop_table("traffit_sync_run_phases")
    op.drop_table("traffit_sync_runs")
    op.drop_table("traffit_webhook_events")
    op.drop_table("traffit_outbox_events")
    op.drop_table("traffit_field_contracts")
    op.drop_table("traffit_entity_links")
    op.drop_table("integration_leases")
    op.drop_table("traffit_integration_control")

    op.drop_index("ix_candidate_documents_manifest", table_name="candidate_documents")
    op.drop_index(
        "ux_candidate_documents_candidate_sha", table_name="candidate_documents"
    )
    op.drop_column("candidate_documents", "source_deleted_at")
    op.drop_column("candidate_documents", "source_manifest_fingerprint")
    op.drop_column("candidate_documents", "content_sha256")

    op.drop_index(
        "ux_rejection_reasons_external_source_id", table_name="rejection_reasons"
    )
    op.drop_index("ix_rejection_reasons_external_id", table_name="rejection_reasons")
    op.drop_index(
        "ix_rejection_reasons_external_source", table_name="rejection_reasons"
    )
    op.drop_column("rejection_reasons", "external_id")
    op.drop_column("rejection_reasons", "external_source")

    op.drop_index("ix_notes_candidate_source_created", table_name="notes")
    op.drop_index("ux_notes_external_source_id", table_name="notes")
    op.drop_index("ix_notes_external_id", table_name="notes")
    op.drop_index("ix_notes_external_source", table_name="notes")
    op.drop_constraint("fk_notes_supersedes_note_id_notes", "notes", type_="foreignkey")
    op.drop_column("notes", "supersedes_note_id")
    op.drop_column("notes", "source_deleted_at")
    op.drop_column("notes", "source_updated_at")
    op.drop_column("notes", "source_created_at")
    op.drop_column("notes", "external_id")
    op.drop_column("notes", "external_source")

    op.drop_column("traffit_sync_state", "next_due_at")
    op.drop_column("traffit_sync_state", "last_error")
    op.drop_column("traffit_sync_state", "consecutive_failures")
    op.drop_column("traffit_sync_state", "last_success_at")
    op.drop_column("traffit_sync_state", "last_attempt_at")
    op.drop_column("traffit_sync_state", "cursor_payload")
    op.drop_column("traffit_sync_state", "cursor_external_id")
    op.drop_column("traffit_sync_state", "cursor_at")

    op.drop_column("candidates", "custom_fields")
    op.drop_column("candidates", "profile_about")
