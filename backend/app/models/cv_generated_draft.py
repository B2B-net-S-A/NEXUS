"""Editable standalone CV; approved artifacts remain in CvDocumentVersion."""

from sqlalchemy import ForeignKey, Integer, LargeBinary, JSON, Text, String
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class CvGeneratedDraft(Base):
    __tablename__ = "cv_generated_drafts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generated_document_id: Mapped[int] = mapped_column(
        ForeignKey("cv_generated_documents.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    edit_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    branded_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    branded_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )
    branded_draft_html: Mapped[str] = mapped_column(Text, nullable=False)
    branded_template_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    branded_consent_content: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    branded_render_metadata: Mapped[dict] = mapped_column(JSON, nullable=False)
    branded_language: Mapped[str] = mapped_column(String(10), nullable=False)
    branded_template: Mapped[str] = mapped_column(String(20), nullable=False)
    branded_docx_filename: Mapped[str] = mapped_column(String(500), nullable=False)
