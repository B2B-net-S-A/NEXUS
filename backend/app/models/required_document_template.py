"""Globalny szablon wymaganego dokumentu klienta (NDA, RODO, off-limits, ...).

Per-klient instancje (z plikiem, statusem) trzymane w `ClientRequiredDocument`.
"""

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class RequiredDocumentTemplate(Base, TimestampMixin):
    """Globalny szablon wymaganego dokumentu — aplikowany do klientów."""

    __tablename__ = "required_document_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return f"<RequiredDocumentTemplate id={self.id} name={self.name!r}>"
