"""Candidate structured fields + RateHistory + CandidateConflict

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-16 10:00:00.000000

Adds Phase 1 structured fields on candidates (years_it_experience, preferences,
champion, verifier_id, verified_tech) and creates two auxiliary tables:

- candidate_rate_history — historical rates per (candidate, client/job)
- candidate_conflicts    — hard-filter blacklist (candidate should not be sent to client)

Backward-compatible: all new columns are nullable or have safe defaults; existing
rows are not modified.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── candidates: add Phase 1 structured columns ─────────────────────────────
    op.add_column(
        "candidates",
        sa.Column("years_it_experience", sa.Integer(), nullable=True),
    )
    op.add_column(
        "candidates",
        sa.Column(
            "preferences", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "candidates",
        sa.Column(
            "champion",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "candidates",
        sa.Column("verifier_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_candidates_verifier_id",
        "candidates",
        "users",
        ["verifier_id"],
        ["id"],
    )
    op.add_column(
        "candidates",
        sa.Column(
            "verified_tech", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )

    # ── candidate_rate_history ────────────────────────────────────────────────
    contracttype = postgresql.ENUM(
        "b2b", "uop", "zlecenie", name="contracttype", create_type=False
    )
    contracttype.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "candidate_rate_history",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id"),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id"),
            nullable=True,
            index=True,
        ),
        sa.Column("rate", sa.Integer(), nullable=False),
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="PLN"
        ),
        sa.Column("contract_type", contracttype, nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "recorded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True
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

    # ── candidate_conflicts ───────────────────────────────────────────────────
    conflicttype = postgresql.ENUM(
        "blacklist",
        "current_employment",
        "nda",
        "competitor",
        name="conflicttype",
        create_type=False,
    )
    conflicttype.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "candidate_conflicts",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("type", conflicttype, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
            index=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
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
    # Partial unique index: only one ACTIVE conflict per (candidate, client)
    op.create_index(
        "uq_candidate_conflict_active",
        "candidate_conflicts",
        ["candidate_id", "client_id"],
        unique=True,
        postgresql_where=sa.text("active = true"),
    )


def downgrade() -> None:
    op.drop_index("uq_candidate_conflict_active", table_name="candidate_conflicts")
    op.drop_table("candidate_conflicts")
    op.execute("DROP TYPE IF EXISTS conflicttype")

    op.drop_table("candidate_rate_history")
    op.execute("DROP TYPE IF EXISTS contracttype")

    op.drop_constraint("fk_candidates_verifier_id", "candidates", type_="foreignkey")
    op.drop_column("candidates", "verified_tech")
    op.drop_column("candidates", "verifier_id")
    op.drop_column("candidates", "champion")
    op.drop_column("candidates", "preferences")
    op.drop_column("candidates", "years_it_experience")
