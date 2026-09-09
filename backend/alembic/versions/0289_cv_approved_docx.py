"""Freeze approved DOCX bytes and generation assets."""

from alembic import op
import sqlalchemy as sa

revision = "0289_cv_approved_docx"
down_revision = "0288_cv_generated_selection"
branch_labels = None
depends_on = None


def upgrade():
    for name, kind in [
        ("branded_template_content", sa.LargeBinary()),
        ("branded_consent_content", sa.LargeBinary()),
        ("branded_docx_filename", sa.String(500)),
        ("branded_render_metadata", sa.JSON()),
    ]:
        op.add_column("candidate_stage_cvs", sa.Column(name, kind, nullable=True))
    for name, kind in [
        ("docx_content", sa.LargeBinary()),
        ("docx_sha256", sa.String(64)),
        ("docx_filename", sa.String(500)),
        ("render_metadata", sa.JSON()),
    ]:
        op.add_column("cv_document_versions", sa.Column(name, kind, nullable=True))


def downgrade():
    for name in ("docx_content", "docx_sha256", "docx_filename", "render_metadata"):
        op.drop_column("cv_document_versions", name)
    for name in (
        "branded_template_content",
        "branded_consent_content",
        "branded_docx_filename",
        "branded_render_metadata",
    ):
        op.drop_column("candidate_stage_cvs", name)
