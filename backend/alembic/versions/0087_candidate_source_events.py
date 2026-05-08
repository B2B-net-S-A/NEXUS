"""Multi-row source attribution per candidate (Traffit gap #4).

Revision ID: 0087_candidate_source_events
Revises: 0086_oauth_clients
Create Date: 2026-05-08 14:00:00.000000

Adds ``candidate_source_events`` so we can record EACH application touch
separately (today ``Candidate.source_enum`` only stores first-touch).
Drives:

- Sidebar on candidate profile (multi-line ``Dodany manualnie • 08/05/2026 /
  E-mail • 09/05/2026`` like Traffit shows).
- /reports/sources aggregation (which channel + UTM bring the most hires).

Why a new ``sourcechannel`` enum (separate from ``candidatesource``):
- ``CandidateSource`` has 6 coarse values (linkedin/pracuj/jjit/...).
  We want richer touch types here (cv_upload, posting, aktywny_search) to
  attribute different funnel paths. Renaming the existing enum + backfilling
  history would touch many files; a parallel enum is cheaper.
"""

from alembic import op
import sqlalchemy as sa


revision = "0087_candidate_source_events"
down_revision = "0086_oauth_clients"
branch_labels = None
depends_on = None


_CHANNELS = (
    "manual",
    "aktywny_search",
    "cv_upload",
    "email",
    "posting",
    "referral",
    "import_csv",
)


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE sourcechannel AS ENUM (
                'manual',
                'aktywny_search',
                'cv_upload',
                'email',
                'posting',
                'referral',
                'import_csv'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    op.create_table(
        "candidate_source_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel",
            sa.Enum(*_CHANNELS, name="sourcechannel", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("utm_source", sa.String(120), nullable=True),
        sa.Column("utm_medium", sa.String(120), nullable=True),
        sa.Column("utm_campaign", sa.String(120), nullable=True),
        sa.Column("utm_term", sa.String(120), nullable=True),
        sa.Column("utm_content", sa.String(120), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_candidate_source_events_candidate_id",
        "candidate_source_events",
        ["candidate_id"],
    )
    op.create_index(
        "ix_candidate_source_events_channel",
        "candidate_source_events",
        ["channel"],
    )
    op.create_index(
        "ix_candidate_source_events_job_id",
        "candidate_source_events",
        ["job_id"],
    )
    op.create_index(
        "ix_candidate_source_events_captured_at",
        "candidate_source_events",
        ["captured_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_candidate_source_events_captured_at",
        table_name="candidate_source_events",
    )
    op.drop_index(
        "ix_candidate_source_events_job_id", table_name="candidate_source_events"
    )
    op.drop_index(
        "ix_candidate_source_events_channel", table_name="candidate_source_events"
    )
    op.drop_index(
        "ix_candidate_source_events_candidate_id",
        table_name="candidate_source_events",
    )
    op.drop_table("candidate_source_events")
    op.execute("DROP TYPE IF EXISTS sourcechannel")
