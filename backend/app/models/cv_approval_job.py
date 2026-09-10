"""Durable edited-CV review attempts, separate from immutable approvals."""

from datetime import datetime
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    LargeBinary,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.base import TimestampMixin


class CvApprovalJob(Base, TimestampMixin):
    __tablename__ = "cv_approval_jobs"
    __table_args__ = (
        CheckConstraint(
            "(generated_draft_id IS NOT NULL) <> (candidate_stage_cv_id IS NOT NULL)",
            name="ck_cv_approval_job_owner",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'verified', 'rejected', 'failed', 'interrupted', 'cancelled')",
            name="ck_cv_approval_job_status",
        ),
        CheckConstraint("expected_revision >= 0", name="ck_cv_approval_job_revision"),
        UniqueConstraint("user_id", "request_key", name="uq_cv_approval_job_request"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    generated_draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_generated_drafts.id", ondelete="CASCADE"), index=True
    )
    candidate_stage_cv_id: Mapped[int | None] = mapped_column(
        ForeignKey("candidate_stage_cvs.id", ondelete="CASCADE"), index=True
    )
    generated_document_id: Mapped[int] = mapped_column(
        ForeignKey("cv_generated_documents.id", ondelete="CASCADE"), nullable=False
    )
    request_key: Mapped[str] = mapped_column(String(36), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", index=True
    )
    # Stored with the document, deleted by the same owner cascade. Never logged.
    input_content: Mapped[bytes | None] = mapped_column(LargeBinary)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
