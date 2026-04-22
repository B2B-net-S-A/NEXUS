"""AI CC matching: candidate M2M CC, job_secondary_cc, overrides, pool->CC, auto_cc removal

Revision ID: 0041_ai_cc_matching
Revises: 0040_talent_pool_source_event
Create Date: 2026-04-22 23:59:00.000000

Rozszerza fundament z `0033_cc_entities` o pełną logikę AI-matchingu:

1. `candidate_competence_categories` — M2M kandydat↔CC (fullstacki w 1 primary + 2 secondary)
2. `job_secondary_cc` — opcjonalne secondary CC per projekt (do wider matching bez kłamania w raportach)
3. `cc_suggestion_overrides` — log overrides gdy DL zmienia sugerowaną CC (feedback loop)
4. `talent_pools.competence_category_id` — pula należy do jednej CC
5. `job_collaborators.removed_from_auto_cc` + `removed_at` — soft-delete dla auto-dodanych

Backfill: kandydaci z non-null legacy `candidate.competence_category_id` → row w M2M z
`is_primary=true, source='manual', confidence_score=1.0`.
"""

from alembic import op
import sqlalchemy as sa


revision = "0041_ai_cc_matching"
down_revision = "0040_talent_pool_source_event"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. Enum: candidate_cc_source ────────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE candidatecccategorysource AS ENUM ('ai_auto', 'ai_suggested', 'manual');
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )

    # ── 2. candidate_competence_categories M2M ──────────────────────────────
    op.create_table(
        "candidate_competence_categories",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "competence_category_id",
            sa.Integer,
            sa.ForeignKey("competence_categories.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "is_primary",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "confidence_score",
            sa.Float,
            nullable=False,
            server_default=sa.text("1.0"),
        ),
        sa.Column(
            "source",
            sa.Enum(
                "ai_auto",
                "ai_suggested",
                "manual",
                name="candidatecccategorysource",
                create_type=False,
            ),
            nullable=False,
            server_default="manual",
        ),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "candidate_id", "competence_category_id", name="uq_candidate_cc"
        ),
        sa.CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="ck_candidate_cc_confidence",
        ),
    )

    # Backfill z legacy candidate.competence_category_id (single FK)
    op.execute(
        """
        INSERT INTO candidate_competence_categories
            (candidate_id, competence_category_id, is_primary, confidence_score, source)
        SELECT id, competence_category_id, true, 1.0, 'manual'
          FROM candidates
         WHERE competence_category_id IS NOT NULL
         ON CONFLICT DO NOTHING;
        """
    )

    # ── 3. job_secondary_cc ─────────────────────────────────────────────────
    op.create_table(
        "job_secondary_cc",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "competence_category_id",
            sa.Integer,
            sa.ForeignKey("competence_categories.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("job_id", "competence_category_id", name="uq_job_secondary_cc"),
    )

    # ── 4. cc_suggestion_overrides ──────────────────────────────────────────
    op.create_table(
        "cc_suggestion_overrides",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "suggested_cc_id",
            sa.Integer,
            sa.ForeignKey("competence_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "final_cc_id",
            sa.Integer,
            sa.ForeignKey("competence_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("suggested_score", sa.Float, nullable=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── 5. talent_pools.competence_category_id ──────────────────────────────
    op.add_column(
        "talent_pools",
        sa.Column(
            "competence_category_id",
            sa.Integer,
            sa.ForeignKey("competence_categories.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
    )

    # ── 6. job_collaborators: removed_from_auto_cc + removed_at ─────────────
    op.add_column(
        "job_collaborators",
        sa.Column(
            "removed_from_auto_cc",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "job_collaborators",
        sa.Column(
            "removed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("job_collaborators", "removed_at")
    op.drop_column("job_collaborators", "removed_from_auto_cc")
    op.drop_column("talent_pools", "competence_category_id")
    op.drop_table("cc_suggestion_overrides")
    op.drop_table("job_secondary_cc")
    op.drop_table("candidate_competence_categories")
    op.execute("DROP TYPE IF EXISTS candidatecccategorysource")
