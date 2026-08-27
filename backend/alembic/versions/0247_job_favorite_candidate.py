"""Add the recruiter's favourite candidate to a recruitment job.

Revision ID: 0247_job_favorite_candidate
Revises: 0246_explicit_order_types
"""

from alembic import op
import sqlalchemy as sa


revision = "0247_job_favorite_candidate"
down_revision = "0246_explicit_order_types"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("favorite_candidate_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_jobs_favorite_candidate_id_candidates",
        "jobs",
        "candidates",
        ["favorite_candidate_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_jobs_favorite_candidate_id",
        "jobs",
        ["favorite_candidate_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_favorite_candidate_id", table_name="jobs")
    op.drop_constraint(
        "fk_jobs_favorite_candidate_id_candidates",
        "jobs",
        type_="foreignkey",
    )
    op.drop_column("jobs", "favorite_candidate_id")
