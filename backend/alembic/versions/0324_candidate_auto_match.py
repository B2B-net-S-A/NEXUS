"""Autonomiczne dopasowanie CV ↔ rekrutacje + zakładanie kandydata z maila.

Revision ID: 0324_candidate_auto_match
Revises: 0323_candidate_skill_usage

- ``candidate_match_outbox`` — trwała kolejka auto-dopasowania;
- ``candidate_auto_match_log`` — decyzja dla każdej rozważonej pary w wersji CV;
- ``notificationtype.auto_match`` — dzwonek „system dodał kandydata";
- ``emailmatchmethod.cv_identity`` — mail podpięty po tożsamości z treści CV.

ADD VALUE w autocommicie (wymóg ALTER TYPE). Zdublowane w safety-necie
`entrypoint.sh` — prod alembic bywa orphaned.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0324_candidate_auto_match"
down_revision = "0323_candidate_skill_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'auto_match'")
        op.execute(
            "ALTER TYPE emailmatchmethod ADD VALUE IF NOT EXISTS 'cv_identity'"
        )

    op.create_table(
        "candidate_match_outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("profile_revision", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "candidate_id IS NOT NULL OR job_id IS NOT NULL",
            name="ck_candidate_match_outbox_subject",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'done', 'failed', 'dead', 'skipped')",
            name="ck_candidate_match_outbox_status",
        ),
    )
    op.create_index(
        "ix_candidate_match_outbox_status_created",
        "candidate_match_outbox",
        ["status", "created_at"],
    )
    op.create_index(
        "ux_candidate_match_outbox_candidate_open",
        "candidate_match_outbox",
        ["candidate_id", "profile_revision"],
        unique=True,
        postgresql_where=sa.text(
            "candidate_id IS NOT NULL AND status IN ('pending', 'processing', 'failed')"
        ),
    )
    op.create_index(
        "ux_candidate_match_outbox_job_open",
        "candidate_match_outbox",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text(
            "job_id IS NOT NULL AND status IN ('pending', 'processing', 'failed')"
        ),
    )

    op.create_table(
        "candidate_auto_match_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("profile_revision", sa.String(64), nullable=False),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("stage_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "candidate_id",
            "job_id",
            "profile_revision",
            name="uq_candidate_auto_match_log_pair_revision",
        ),
    )
    op.create_index(
        "ix_candidate_auto_match_log_job", "candidate_auto_match_log", ["job_id"]
    )
    op.create_index(
        "ix_candidate_auto_match_log_created",
        "candidate_auto_match_log",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_table("candidate_auto_match_log")
    op.drop_table("candidate_match_outbox")
