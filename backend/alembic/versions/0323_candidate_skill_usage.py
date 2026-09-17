"""Indeks użycia technologii kandydata (odczyt CV v7).

Revision ID: 0323_candidate_skill_usage
Revises: 0322_dl_alert_conflict_expired

Tabela pochodna z `cv_extracted_data.skill_timeline`: kiedy i gdzie kandydat
używał danej technologii. Pisana wyłącznie przez
`profile_projection.replace_skill_usage`. Zdublowana w safety-necie
`entrypoint.sh` — prod alembic bywa orphaned.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0323_candidate_skill_usage"
down_revision = "0322_dl_alert_conflict_expired"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "candidate_skill_usage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("skill_canonical", sa.String(120), nullable=False),
        sa.Column("skill_raw", sa.String(120), nullable=False),
        sa.Column("first_used", sa.Date(), nullable=True),
        sa.Column("last_used", sa.Date(), nullable=True),
        sa.Column("months", sa.Integer(), nullable=True),
        sa.Column(
            "is_current", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "contexts", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "provenance", sa.String(16), nullable=False, server_default="cv"
        ),
        sa.Column("source_ref", sa.String(120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "candidate_id",
            "skill_canonical",
            name="uq_candidate_skill_usage_candidate_skill",
        ),
        sa.CheckConstraint(
            "provenance IN ('cv', 'manual')",
            name="ck_candidate_skill_usage_provenance",
        ),
    )
    op.create_index(
        "ix_candidate_skill_usage_candidate_id",
        "candidate_skill_usage",
        ["candidate_id"],
    )
    op.create_index(
        "ix_candidate_skill_usage_skill_last_used",
        "candidate_skill_usage",
        ["skill_canonical", "last_used"],
    )


def downgrade() -> None:
    op.drop_table("candidate_skill_usage")
