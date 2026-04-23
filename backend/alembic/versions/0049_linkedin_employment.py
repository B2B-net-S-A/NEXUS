"""LinkedIn employment tracking: candidate fields + snapshots table

Revision ID: 0049_linkedin_employment
Revises: 0048_job_close_reason
Create Date: 2026-04-23 14:00:00.000000

Adds schema backing the "recently changed jobs" feature:

- `candidates`: 7 new columns (linkedin_current_company, linkedin_current_title,
  linkedin_current_started_at, linkedin_employment_changed_at, linkedin_synced_at,
  linkedin_sync_status, linkedin_sync_error) — denormalized fast-path for badge
  rendering and filter queries.
- `candidate_linkedin_snapshots` (new table) — one row per successful Proxycurl
  fetch, storing the full profile JSON + derived fields + diff result
  (change_kind). Enables retroactive re-analysis without re-paying Proxycurl.
- Enum types: `linkedinsyncstatus`, `linkedinchangekind`.

Idempotent + reversible. Existing candidate rows get `linkedin_sync_status =
'disabled'` via server_default (kept so even after removing the default the
historical rows still have a value).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0049_linkedin_employment"
down_revision = "0048_job_close_reason"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enum types (idempotent) ───────────────────────────────────────────
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'linkedinsyncstatus') THEN
                CREATE TYPE linkedinsyncstatus AS ENUM (
                    'ok', 'not_found', 'error', 'rate_limited', 'disabled'
                );
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'linkedinchangekind') THEN
                CREATE TYPE linkedinchangekind AS ENUM (
                    'first_snapshot', 'no_change',
                    'new_company', 'new_title_same_company'
                );
            END IF;
        END$$;
        """
    )

    # ── candidates: new columns ───────────────────────────────────────────
    op.add_column(
        "candidates",
        sa.Column("linkedin_current_company", sa.String(255), nullable=True),
    )
    op.add_column(
        "candidates",
        sa.Column("linkedin_current_title", sa.String(255), nullable=True),
    )
    op.add_column(
        "candidates",
        sa.Column("linkedin_current_started_at", sa.Date(), nullable=True),
    )
    op.add_column(
        "candidates",
        sa.Column(
            "linkedin_employment_changed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "candidates",
        sa.Column(
            "linkedin_synced_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "candidates",
        sa.Column(
            "linkedin_sync_status",
            postgresql.ENUM(
                "ok",
                "not_found",
                "error",
                "rate_limited",
                "disabled",
                name="linkedinsyncstatus",
                create_type=False,
            ),
            server_default="disabled",
            nullable=False,
        ),
    )
    op.add_column(
        "candidates",
        sa.Column("linkedin_sync_error", sa.Text(), nullable=True),
    )

    # Indexes powering the new filters / stale-query / search path.
    op.create_index(
        "ix_candidates_linkedin_current_company",
        "candidates",
        ["linkedin_current_company"],
    )
    op.create_index(
        "ix_candidates_linkedin_employment_changed_at",
        "candidates",
        ["linkedin_employment_changed_at"],
    )
    op.create_index(
        "ix_candidates_linkedin_synced_at",
        "candidates",
        ["linkedin_synced_at"],
    )

    # ── candidate_linkedin_snapshots (new table) ──────────────────────────
    op.create_table(
        "candidate_linkedin_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "profile_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("current_company", sa.String(255), nullable=True),
        sa.Column("current_title", sa.String(255), nullable=True),
        sa.Column("current_started_at", sa.Date(), nullable=True),
        sa.Column(
            "changed_from_previous",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "change_kind",
            postgresql.ENUM(
                "first_snapshot",
                "no_change",
                "new_company",
                "new_title_same_company",
                name="linkedinchangekind",
                create_type=False,
            ),
            server_default="first_snapshot",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_linkedin_snap_candidate_fetched",
        "candidate_linkedin_snapshots",
        ["candidate_id", "fetched_at"],
    )


def downgrade() -> None:
    # Drop snapshot table + its indexes.
    op.execute("DROP INDEX IF EXISTS ix_linkedin_snap_candidate_fetched")
    op.drop_table("candidate_linkedin_snapshots")

    # Drop candidate indexes then columns (reverse order).
    for idx in (
        "ix_candidates_linkedin_synced_at",
        "ix_candidates_linkedin_employment_changed_at",
        "ix_candidates_linkedin_current_company",
    ):
        op.execute(f"DROP INDEX IF EXISTS {idx}")

    for col in (
        "linkedin_sync_error",
        "linkedin_sync_status",
        "linkedin_synced_at",
        "linkedin_employment_changed_at",
        "linkedin_current_started_at",
        "linkedin_current_title",
        "linkedin_current_company",
    ):
        op.drop_column("candidates", col)

    # Drop enum types last (tables / columns using them are gone).
    op.execute("DROP TYPE IF EXISTS linkedinchangekind")
    op.execute("DROP TYPE IF EXISTS linkedinsyncstatus")
