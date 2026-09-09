"""Immutable approved document; links reference a version, never a live draft."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    LargeBinary,
    JSON,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CvDocumentVersion(Base):
    __tablename__ = "cv_document_versions"
    __table_args__ = (UniqueConstraint("candidate_stage_cv_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_stage_cv_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_stage_cvs.id", ondelete="CASCADE"), index=True
    )
    generated_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_generated_documents.id", ondelete="SET NULL"), nullable=True
    )
    docx_content: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    docx_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    docx_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    render_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content_html: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    template: Mapped[str | None] = mapped_column(String(20))
    language: Mapped[str | None] = mapped_column(String(10))
    candidate_first_name: Mapped[str | None] = mapped_column(String(300))
    job_title: Mapped[str | None] = mapped_column(String(500))
    snapshot_path: Mapped[str | None] = mapped_column(String(512))
    snapshot_filename: Mapped[str | None] = mapped_column(String(500))
    snapshot_size_bytes: Mapped[int | None] = mapped_column(Integer)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    approved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
