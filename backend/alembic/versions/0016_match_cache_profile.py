"""Phase D1: match score cache keyed by profile_id

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-17 14:00:00.000000

Lets the cache store different scores for the same (candidate, job) pair under
different scoring weight profiles. `profile_id = 0` is the sentinel for the
built-in default profile; real profiles use their row id from
`scoring_weight_profiles`.
"""

from alembic import op
import sqlalchemy as sa


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "candidate_job_match_scores",
        sa.Column(
            "profile_id",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    # Replace PK to include profile_id.
    op.execute(
        "ALTER TABLE candidate_job_match_scores "
        "DROP CONSTRAINT pk_candidate_job_match_scores"
    )
    op.create_primary_key(
        "pk_candidate_job_match_scores",
        "candidate_job_match_scores",
        ["candidate_id", "job_id", "profile_id"],
    )
    # Rebuild top-N indexes scoped per profile.
    op.drop_index(
        "ix_match_scores_job_topn", table_name="candidate_job_match_scores"
    )
    op.drop_index(
        "ix_match_scores_candidate_topn", table_name="candidate_job_match_scores"
    )
    op.create_index(
        "ix_match_scores_job_profile_topn",
        "candidate_job_match_scores",
        ["job_id", "profile_id", sa.text("total_score DESC")],
    )
    op.create_index(
        "ix_match_scores_candidate_profile_topn",
        "candidate_job_match_scores",
        ["candidate_id", "profile_id", sa.text("total_score DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_match_scores_candidate_profile_topn",
        table_name="candidate_job_match_scores",
    )
    op.drop_index(
        "ix_match_scores_job_profile_topn", table_name="candidate_job_match_scores"
    )
    op.create_index(
        "ix_match_scores_job_topn",
        "candidate_job_match_scores",
        ["job_id", sa.text("total_score DESC")],
    )
    op.create_index(
        "ix_match_scores_candidate_topn",
        "candidate_job_match_scores",
        ["candidate_id", sa.text("total_score DESC")],
    )
    op.execute(
        "ALTER TABLE candidate_job_match_scores "
        "DROP CONSTRAINT pk_candidate_job_match_scores"
    )
    op.create_primary_key(
        "pk_candidate_job_match_scores",
        "candidate_job_match_scores",
        ["candidate_id", "job_id"],
    )
    op.drop_column("candidate_job_match_scores", "profile_id")
