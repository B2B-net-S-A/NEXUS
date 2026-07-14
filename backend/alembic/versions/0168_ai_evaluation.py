"""Add blind AI evaluation workflow and OpenAI challenger feature.

Revision ID: 0168_ai_evaluation
Revises: 0167_embedding_cache_identity
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0168_ai_evaluation"
down_revision = "0167_embedding_cache_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL requires a newly added enum value to be committed before it
    # can be used by the seed INSERT below.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'cv_parser_challenger'"
        )
    op.execute(
        """INSERT INTO ai_features
           (feature, enabled, monthly_limit, monthly_budget_usd, created_at, updated_at)
           VALUES ('cv_parser_challenger', false, 0, 0, now(), now())
           ON CONFLICT (feature) DO NOTHING"""
    )
    op.create_table(
        "ai_eval_sets",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("frozen", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ai_eval_sets_feature", "ai_eval_sets", ["feature"])
    op.create_table(
        "ai_eval_cases",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "eval_set_id",
            sa.BigInteger(),
            sa.ForeignKey("ai_eval_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_ref",
            sa.String(128),
            nullable=False,
            server_default="candidate.raw_cv_text",
        ),
        sa.Column(
            "slice_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "eval_set_id", "candidate_id", "source_ref", name="uq_ai_eval_case_ref"
        ),
    )
    op.create_index("ix_ai_eval_cases_eval_set_id", "ai_eval_cases", ["eval_set_id"])
    op.create_index("ix_ai_eval_cases_candidate_id", "ai_eval_cases", ["candidate_id"])
    op.create_table(
        "ai_eval_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "eval_set_id",
            sa.BigInteger(),
            sa.ForeignKey("ai_eval_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="offline"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("champion_provider", sa.String(32), nullable=False),
        sa.Column("champion_model", sa.String(128), nullable=False),
        sa.Column("challenger_provider", sa.String(32), nullable=False),
        sa.Column("challenger_model", sa.String(128), nullable=False),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("mode IN ('offline','shadow')", name="ck_ai_eval_run_mode"),
        sa.CheckConstraint(
            "status IN ('draft','running','review','completed','failed')",
            name="ck_ai_eval_run_status",
        ),
    )
    op.create_index("ix_ai_eval_runs_eval_set_id", "ai_eval_runs", ["eval_set_id"])
    op.create_table(
        "ai_eval_labels",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("ai_eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.BigInteger(),
            sa.ForeignKey("ai_eval_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("preferred_variant", sa.String(1)),
        sa.Column("rating_a", sa.Integer()),
        sa.Column("rating_b", sa.Integer()),
        sa.Column(
            "metrics",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("comment", sa.Text()),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "run_id", "case_id", "reviewer_id", name="uq_ai_eval_reviewer_case"
        ),
        sa.CheckConstraint(
            "preferred_variant IS NULL OR preferred_variant IN ('A','B')",
            name="ck_ai_eval_preferred_variant",
        ),
        sa.CheckConstraint(
            "rating_a IS NULL OR rating_a BETWEEN 1 AND 5", name="ck_ai_eval_rating_a"
        ),
        sa.CheckConstraint(
            "rating_b IS NULL OR rating_b BETWEEN 1 AND 5", name="ck_ai_eval_rating_b"
        ),
    )
    for column in ("run_id", "case_id", "reviewer_id"):
        op.create_index(f"ix_ai_eval_labels_{column}", "ai_eval_labels", [column])
    op.create_table(
        "ai_eval_outputs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "run_id",
            sa.BigInteger(),
            sa.ForeignKey("ai_eval_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "case_id",
            sa.BigInteger(),
            sa.ForeignKey("ai_eval_cases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variant", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=False),
        sa.Column(
            "deterministic_metrics",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "case_id", "variant", name="uq_ai_eval_output"),
        sa.CheckConstraint(
            "variant IN ('champion','challenger')", name="ck_ai_eval_output_variant"
        ),
    )
    for column in ("run_id", "case_id", "expires_at"):
        op.create_index(f"ix_ai_eval_outputs_{column}", "ai_eval_outputs", [column])


def downgrade() -> None:
    op.drop_table("ai_eval_outputs")
    op.drop_table("ai_eval_labels")
    op.drop_table("ai_eval_runs")
    op.drop_table("ai_eval_cases")
    op.drop_table("ai_eval_sets")
