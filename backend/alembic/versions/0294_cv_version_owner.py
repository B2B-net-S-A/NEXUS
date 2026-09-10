"""Allow the same approved artifact model to belong to standalone generation."""

from alembic import op
import sqlalchemy as sa

revision = "0294_cv_version_owner"
down_revision = "0293_cv_share_version"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cv_document_versions",
        sa.Column(
            "generated_owner_id",
            sa.Integer(),
            sa.ForeignKey("cv_generated_documents.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    op.alter_column(
        "cv_document_versions",
        "candidate_stage_cv_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_check_constraint(
        "ck_cv_version_owner",
        "cv_document_versions",
        "(candidate_stage_cv_id IS NOT NULL) <> (generated_owner_id IS NOT NULL)",
    )
    op.create_index(
        "uq_cv_generated_version",
        "cv_document_versions",
        ["generated_owner_id", "version"],
        unique=True,
        postgresql_where=sa.text("candidate_stage_cv_id IS NULL"),
    )


def downgrade():
    # Existing standalone approvals must be explicitly retained/mapped before rollback.
    op.alter_column(
        "cv_document_versions",
        "candidate_stage_cv_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.drop_index("uq_cv_generated_version", table_name="cv_document_versions")
    op.drop_constraint("ck_cv_version_owner", "cv_document_versions", type_="check")

    op.drop_column("cv_document_versions", "generated_owner_id")
