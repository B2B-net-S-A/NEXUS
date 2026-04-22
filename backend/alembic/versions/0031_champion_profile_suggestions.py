"""Champion Profile AI suggestions (Phase 14 — AI Intake)

Revision ID: 0031_champion_profile_suggestions
Revises: notif_triggers_13
Create Date: 2026-04-21 20:00:00.000000

Stores AI-generated drafts of the Champion Profile that a Delivery Lead
reviews and either applies (per section) or rejects. Sources can be:
  - `jd_paste`              raw client job description pasted by DL
  - `fireflies_meeting`     transcript imported from Fireflies (HM / konsultant)
  - `cloudtalk_call`        call recording transcript pushed from CloudTalk
  - `manual_consultant_note` free-form note entered in UI (future)

Design notes
------------
* `payload` JSONB stores a delta per section:
  { "<section_name>": { "value": <any>, "confidence": 0..1, "rationale": "..."} }
  Sections mirror ChampionProfile schema (basics, project_context,
  screening_questions, historical_client_questions, internal_consultant_insight,
  sourcing).
* `status=pending` is the initial state; moved to accepted / rejected /
  partially_accepted on DL action, or `superseded` when a newer suggestion
  with the same source_type/job_id arrives.
* Two indexes support the UI's two main reads:
    (job_id, status)              — pending suggestions list per job
    (job_id, created_at DESC)     — activity feed per job

Note on down_revision: the repo has several orphan 0029/0030 heads; we chain
to the revision that is actually applied in DB so this migration can run in
dev/prod. A future merge revision should reconcile the diverging heads.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0031_champion_profile_suggestions"
down_revision = "notif_triggers_13"
branch_labels = None
depends_on = None


SOURCE_TYPE_VALUES = (
    "jd_paste",
    "fireflies_meeting",
    "cloudtalk_call",
    "manual_consultant_note",
)

STATUS_VALUES = (
    "pending",
    "accepted",
    "rejected",
    "partially_accepted",
    "superseded",
)


def upgrade() -> None:
    # Create Postgres ENUM types explicitly. Using IF NOT EXISTS (via DO block)
    # so the migration is safe if a previous run partially created them.
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE champion_suggestion_source AS ENUM "
        f"({', '.join(repr(v) for v in SOURCE_TYPE_VALUES)}); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    )
    op.execute(
        "DO $$ BEGIN "
        "CREATE TYPE champion_suggestion_status AS ENUM "
        f"({', '.join(repr(v) for v in STATUS_VALUES)}); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$;"
    )

    source_type_col = postgresql.ENUM(
        *SOURCE_TYPE_VALUES,
        name="champion_suggestion_source",
        create_type=False,
    )
    status_col = postgresql.ENUM(
        *STATUS_VALUES,
        name="champion_suggestion_status",
        create_type=False,
    )

    op.create_table(
        "champion_profile_suggestions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", source_type_col, nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "status",
            status_col,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "created_by_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "reviewed_by_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model_name", sa.String(length=64), nullable=True),
        sa.Column("prompt_version", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    op.create_index(
        "ix_champion_suggestions_job_status",
        "champion_profile_suggestions",
        ["job_id", "status"],
    )
    op.create_index(
        "ix_champion_suggestions_job_created_at",
        "champion_profile_suggestions",
        ["job_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_champion_suggestions_job_created_at",
        table_name="champion_profile_suggestions",
    )
    op.drop_index(
        "ix_champion_suggestions_job_status",
        table_name="champion_profile_suggestions",
    )
    op.drop_table("champion_profile_suggestions")
    op.execute("DROP TYPE IF EXISTS champion_suggestion_status")
    op.execute("DROP TYPE IF EXISTS champion_suggestion_source")
