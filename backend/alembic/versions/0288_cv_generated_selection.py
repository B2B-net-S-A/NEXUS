"""Explicit generated-document selection for a recruitment draft."""

from alembic import op
import sqlalchemy as sa

revision = "0288_cv_generated_selection"
down_revision = "0287_cv_document_versions"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "candidate_stage_cvs",
        sa.Column(
            "generated_document_id",
            sa.Integer(),
            sa.ForeignKey("cv_generated_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "candidate_stage_cvs",
        sa.Column(
            "branded_from_generator",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_index(
        "ix_candidate_stage_cvs_generated_document_id",
        "candidate_stage_cvs",
        ["generated_document_id"],
    )


def downgrade():
    op.drop_index(
        "ix_candidate_stage_cvs_generated_document_id", table_name="candidate_stage_cvs"
    )
    op.drop_column("candidate_stage_cvs", "branded_from_generator")
    op.drop_column("candidate_stage_cvs", "generated_document_id")
