"""Durable requirement-map attempt owned by one immutable CV version."""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    JSON,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CvVersionMap(Base):
    __tablename__ = "cv_version_maps"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'failed', 'interrupted')",
            name="ck_cv_version_map_status",
        ),
    )
    document_version_id: Mapped[int] = mapped_column(
        ForeignKey("cv_document_versions.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    input_content: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", index=True
    )
    result: Mapped[dict | None] = mapped_column(JSON)
    error_code: Mapped[str | None] = mapped_column(String(64))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
