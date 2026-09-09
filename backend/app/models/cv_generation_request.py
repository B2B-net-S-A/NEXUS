"""Idempotency receipt committed atomically with the generated job and admission."""

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.base import TimestampMixin


class CvGenerationRequest(Base, TimestampMixin):
    __tablename__ = "cv_generation_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "request_key", name="uq_cv_generation_request"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    request_key: Mapped[str] = mapped_column(String(36), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_generated_documents.id", ondelete="SET NULL"), nullable=True
    )
