"""Durable ownership of a CV generation attempt and its private input snapshot.

Only queued attempts can be claimed. An expired running attempt is interrupted,
never automatically replayed: its last provider request may already be billed.
"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class CvGenerationJob(Base, TimestampMixin):
    __tablename__ = "cv_generation_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'failed', 'interrupted')",
            name="ck_cv_generation_job_status",
        ),
        CheckConstraint(
            "kind IN ('new', 'upload', 'preview')", name="ck_cv_generation_job_kind"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generated_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_generated_documents.id", ondelete="CASCADE"), unique=True
    )
    second_generated_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_generated_documents.id", ondelete="SET NULL"), unique=True
    )
    preview_id: Mapped[int | None] = mapped_column(
        ForeignKey("client_cv_rule_previews.id", ondelete="CASCADE"), unique=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", index=True
    )
    input_storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    quota_snapshot: Mapped[dict | None] = mapped_column(JSON())
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
