"""Job collaborators (many-to-many user↔job, in addition to primary recruiter_id)

Revision ID: 0029
Revises: 0028
Create Date: 2026-04-21 10:00:00.000000

Adds `job_collaborators` — the secondary ownership layer. Primary ownership
stays on `jobs.recruiter_id` (single nullable FK); collaborators are "people
on this project who should see it in Moje projekty" without holding the
primary accountability.

    job_collaborators
      id         SERIAL PK
      job_id     FK jobs(id)   ON DELETE CASCADE
      user_id    FK users(id)  ON DELETE CASCADE
      added_by   FK users(id)  (nullable)
      added_at   TIMESTAMPTZ   default now()
      UNIQUE (job_id, user_id)

Two supporting indexes:
  ix_job_collaborators_user — fast "give me every job I collaborate on"
  ix_job_collaborators_job  — fast "who collaborates on this job" (also served by UNIQUE)
"""

from alembic import op
import sqlalchemy as sa


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_collaborators",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "added_by",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("job_id", "user_id", name="uq_job_collaborators_job_user"),
    )
    op.create_index(
        "ix_job_collaborators_user", "job_collaborators", ["user_id"]
    )
    op.create_index(
        "ix_job_collaborators_job", "job_collaborators", ["job_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_job_collaborators_job", table_name="job_collaborators")
    op.drop_index("ix_job_collaborators_user", table_name="job_collaborators")
    op.drop_table("job_collaborators")
