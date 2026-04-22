"""Candidate invite links — self-service application links with ownership

Revision ID: 0031_candidate_invite_links
Revises: 0030_candidate_created_by
Create Date: 2026-04-21 19:00:00.000000

Recruiter generates a multi-use, job-scoped, time-limited link. Candidate
applies through /apply/{token}. The candidate row is created (or merged on
email match) with `created_by = link.created_by` so ownership is attributed
to the recruiter who acquired them.

Pattern mirrors champion_card_share_tokens (migration 0028). Idempotent +
reversible.
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_candidate_invite_links"
down_revision = "0030_candidate_created_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_invite_links",
        sa.Column("token", sa.Text, primary_key=True),
        sa.Column(
            "created_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "revoked",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "use_count",
            sa.Integer,
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_invite_links_created_by "
        "ON candidate_invite_links(created_by)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_invite_links_job_id "
        "ON candidate_invite_links(job_id)"
    )
    # Partial index for the "active, non-revoked" lookup path.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_invite_links_live "
        "ON candidate_invite_links(token) "
        "WHERE revoked IS FALSE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidate_invite_links_live")
    op.execute("DROP INDEX IF EXISTS ix_candidate_invite_links_job_id")
    op.execute("DROP INDEX IF EXISTS ix_candidate_invite_links_created_by")
    op.drop_table("candidate_invite_links")
