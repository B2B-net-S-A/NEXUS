"""Job structured fields for matching engine

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-16 10:30:00.000000

Adds Phase 1 structured fields on jobs:

- must_skills / nice_skills    — structured criteria (matching-engine input)
- seniority, work_mode         — new enums
- headcount, reference_number  — B2B staffing metadata
- industry, subcategory        — hierarchical taxonomy
- custom_fields                — freeform JSONB (Faza 4 will replace with a dedicated engine)
- embedding_id                 — persisted Qdrant vector id (populated by Faza 2)
- criteria_generated_at        — timestamp of last AI criteria refresh

All fields are nullable or have safe defaults; existing rows are preserved.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    seniority = postgresql.ENUM(
        "junior",
        "mid",
        "senior",
        "lead",
        "architect",
        name="seniority",
        create_type=False,
    )
    seniority.create(op.get_bind(), checkfirst=True)

    workmode = postgresql.ENUM(
        "fulltime",
        "parttime",
        "contract",
        name="workmode",
        create_type=False,
    )
    workmode.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "jobs",
        sa.Column(
            "must_skills", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "nice_skills", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column("jobs", sa.Column("seniority", seniority, nullable=True))
    op.add_column(
        "jobs",
        sa.Column(
            "work_mode",
            workmode,
            nullable=False,
            server_default="fulltime",
        ),
    )
    op.add_column(
        "jobs",
        sa.Column(
            "headcount",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.add_column(
        "jobs",
        sa.Column("reference_number", sa.String(length=50), nullable=True),
    )
    op.add_column("jobs", sa.Column("industry", sa.String(length=50), nullable=True))
    op.add_column(
        "jobs", sa.Column("subcategory", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "jobs",
        sa.Column(
            "custom_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )
    op.add_column(
        "jobs", sa.Column("embedding_id", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "jobs",
        sa.Column("criteria_generated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Unique only when reference_number is not null
    op.create_index(
        "uq_jobs_reference_number",
        "jobs",
        ["reference_number"],
        unique=True,
        postgresql_where=sa.text("reference_number IS NOT NULL"),
    )
    op.create_index(
        "ix_jobs_industry", "jobs", ["industry"], unique=False, if_not_exists=True
    )
    op.create_index(
        "ix_jobs_embedding_id",
        "jobs",
        ["embedding_id"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_embedding_id", table_name="jobs")
    op.drop_index("ix_jobs_industry", table_name="jobs")
    op.drop_index("uq_jobs_reference_number", table_name="jobs")

    op.drop_column("jobs", "criteria_generated_at")
    op.drop_column("jobs", "embedding_id")
    op.drop_column("jobs", "custom_fields")
    op.drop_column("jobs", "subcategory")
    op.drop_column("jobs", "industry")
    op.drop_column("jobs", "reference_number")
    op.drop_column("jobs", "headcount")
    op.drop_column("jobs", "work_mode")
    op.drop_column("jobs", "seniority")
    op.drop_column("jobs", "nice_skills")
    op.drop_column("jobs", "must_skills")

    op.execute("DROP TYPE IF EXISTS workmode")
    op.execute("DROP TYPE IF EXISTS seniority")
