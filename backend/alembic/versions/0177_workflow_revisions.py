"""Wersjonowane workflow — shadow-tabele (M4 audyt P0.2/P1.2, plan PR-05).

``workflow_definitions`` / ``workflow_revisions`` / ``stage_revisions`` /
``workflow_edges`` — fundament pod RecruitmentProcess (PR-06) i command
service (PR-07). W tym PR runtime NIC z nich nie czyta (shadow); bootstrap
wypełnia je z legacy templates przez admin endpoint.

Wszystko idempotentne (IF NOT EXISTS) — mirror w ``backend/entrypoint.sh``
(prod alembic orphaned).

Revision ID: 0177_workflow_revisions
Revises: 0176_cv_share_token_v2
"""

from alembic import op

revision = "0177_workflow_revisions"
down_revision = "0176_cv_share_token_v2"
branch_labels = None
depends_on = None

STATEMENTS = [
    """DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_type WHERE typname = 'workflowrevisionstatus'
        ) THEN
            CREATE TYPE workflowrevisionstatus AS ENUM (
                'draft', 'published', 'archived'
            );
        END IF;
    END $$""",
    """CREATE TABLE IF NOT EXISTS workflow_definitions (
        id SERIAL PRIMARY KEY,
        template_id INTEGER NULL UNIQUE
            REFERENCES pipeline_templates(id) ON DELETE SET NULL,
        name VARCHAR(100) NOT NULL,
        description TEXT NULL,
        client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
        archived BOOLEAN NOT NULL DEFAULT FALSE,
        created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )""",
    "CREATE INDEX IF NOT EXISTS ix_workflow_defs_client "
    "ON workflow_definitions (client_id)",
    """CREATE TABLE IF NOT EXISTS workflow_revisions (
        id SERIAL PRIMARY KEY,
        workflow_id INTEGER NOT NULL
            REFERENCES workflow_definitions(id) ON DELETE CASCADE,
        revision_no INTEGER NOT NULL,
        status workflowrevisionstatus NOT NULL DEFAULT 'draft',
        source VARCHAR(50) NULL,
        registry_version VARCHAR(30) NULL,
        published_at TIMESTAMPTZ NULL,
        published_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_workflow_rev_no UNIQUE (workflow_id, revision_no)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_workflow_revs_workflow "
    "ON workflow_revisions (workflow_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_workflow_one_published "
    "ON workflow_revisions (workflow_id) WHERE status = 'published'",
    """CREATE TABLE IF NOT EXISTS stage_revisions (
        id SERIAL PRIMARY KEY,
        workflow_revision_id INTEGER NOT NULL
            REFERENCES workflow_revisions(id) ON DELETE CASCADE,
        source_stage_def_id INTEGER NULL
            REFERENCES pipeline_stage_defs(id) ON DELETE SET NULL,
        name VARCHAR(100) NOT NULL,
        "order" INTEGER NOT NULL,
        category VARCHAR(20) NOT NULL,
        semantic_key VARCHAR(50) NOT NULL,
        is_terminal BOOLEAN NOT NULL DEFAULT FALSE,
        terminal_type VARCHAR(20) NULL,
        tracker_enabled BOOLEAN NOT NULL DEFAULT FALSE,
        tracker_public_name VARCHAR(100) NULL,
        sla_max_days INTEGER NULL,
        scorecard_schema JSONB NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CONSTRAINT uq_stage_rev_order UNIQUE (workflow_revision_id, "order"),
        CONSTRAINT uq_stage_rev_name UNIQUE (workflow_revision_id, name)
    )""",
    "CREATE INDEX IF NOT EXISTS ix_stage_revs_revision "
    "ON stage_revisions (workflow_revision_id)",
    "CREATE INDEX IF NOT EXISTS ix_stage_revs_semantic "
    "ON stage_revisions (semantic_key)",
    "CREATE INDEX IF NOT EXISTS ix_stage_revs_source "
    "ON stage_revisions (source_stage_def_id)",
    """CREATE TABLE IF NOT EXISTS workflow_edges (
        id SERIAL PRIMARY KEY,
        workflow_revision_id INTEGER NOT NULL
            REFERENCES workflow_revisions(id) ON DELETE CASCADE,
        from_stage_revision_id INTEGER NULL
            REFERENCES stage_revisions(id) ON DELETE CASCADE,
        to_stage_revision_id INTEGER NOT NULL
            REFERENCES stage_revisions(id) ON DELETE CASCADE,
        CONSTRAINT uq_workflow_edge UNIQUE (
            workflow_revision_id, from_stage_revision_id, to_stage_revision_id
        )
    )""",
    "CREATE INDEX IF NOT EXISTS ix_workflow_edges_revision "
    "ON workflow_edges (workflow_revision_id)",
]


def upgrade() -> None:
    for stmt in STATEMENTS:
        op.execute(stmt)


def downgrade() -> None:
    for table in (
        "workflow_edges",
        "stage_revisions",
        "workflow_revisions",
        "workflow_definitions",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table}")
    op.execute("DROP TYPE IF EXISTS workflowrevisionstatus")
