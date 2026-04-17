"""Phase C1: candidate_job_match_scores — cache table for hybrid score breakdowns

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-17 12:30:00.000000

Materializes the output of `scoring_service.score_candidate_job` so repeat
fetches of /jobs/{id}/recommendations are sub-100ms instead of recomputing
on every call. `stale=true` rows are recomputed lazily (read-through) or
via a batch job after candidate/job edits.

Schema
------
candidate_job_match_scores
  candidate_id     int FK -> candidates(id) ON DELETE CASCADE
  job_id           int FK -> jobs(id) ON DELETE CASCADE
  total_score      real
  breakdown        jsonb          (full ScoreBreakdown.as_dict())
  scored_at        timestamptz   default now()
  stale            boolean        default false
  PRIMARY KEY (candidate_id, job_id)
  INDEX (job_id, total_score DESC)     -- hot path: job → top-N candidates
  INDEX (candidate_id, total_score DESC) -- reverse: candidate → top-N jobs
  INDEX (stale) WHERE stale IS TRUE     -- recompute worker sweep
"""

from alembic import op
import sqlalchemy as sa


revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_job_match_scores",
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("total_score", sa.Float, nullable=False),
        sa.Column("breakdown", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column(
            "scored_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "stale",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("candidate_id", "job_id", name="pk_candidate_job_match_scores"),
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
        "CREATE INDEX ix_match_scores_stale ON candidate_job_match_scores (stale) WHERE stale IS TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_match_scores_stale")
    op.drop_index(
        "ix_match_scores_candidate_topn", table_name="candidate_job_match_scores"
    )
    op.drop_index(
        "ix_match_scores_job_topn", table_name="candidate_job_match_scores"
    )
    op.drop_table("candidate_job_match_scores")
