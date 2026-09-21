"""Skrzynka „Propozycje" rekrutacji: job_proposals + job_proposal_seen.

Revision ID: 0330_job_proposals
Revises: 0329_candidate_search_completed_notif

- ``job_proposals`` — kandydat zaproponowany do rekrutacji przez jedno źródło;
  UNIQUE (job_id, candidate_id, source). ``run_id`` bez FK — przeglądy kasuje
  retencja, propozycja ma ją przeżyć. Kandydat i rekrutacja: ON DELETE CASCADE
  (twarde usunięcie kandydata zabiera jego propozycje — RODO).
- ``job_proposal_seen`` — znacznik „widziane do" per (osoba, rekrutacja).

Zdublowane w safety-necie ``entrypoint.sh`` (``_COLUMN_STATEMENTS``) — prod
alembic bywa orphaned. Lustro pilnuje ``tests/test_job_proposals.py``.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0330_job_proposals"
down_revision = "0329_candidate_search_completed_notif"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_proposals",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column("evidence", JSONB(), nullable=True),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column(
            "first_seen_at",
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
        sa.Column(
            "dismissed_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "job_id", "candidate_id", "source", name="uq_job_proposals_pair_source"
        ),
        sa.CheckConstraint(
            "source IN ('full_base', 'new_cv', 'similar_projects', "
            "'recommendation', 'marketplace')",
            name="ck_job_proposals_source",
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'dismissed', 'added')",
            name="ck_job_proposals_status",
        ),
    )
    op.create_index(
        "ix_job_proposals_job_status_seen",
        "job_proposals",
        ["job_id", "status", "first_seen_at"],
    )
    op.create_index("ix_job_proposals_candidate_id", "job_proposals", ["candidate_id"])

    op.create_table(
        "job_proposal_seen",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("job_proposal_seen")
    op.drop_index("ix_job_proposals_candidate_id", table_name="job_proposals")
    op.drop_index("ix_job_proposals_job_status_seen", table_name="job_proposals")
    op.drop_table("job_proposals")
