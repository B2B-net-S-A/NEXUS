"""Sales-material one-pager files uploaded against a client (PDF/DOCX)."""

from typing import Optional

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ClientOnePager(Base, TimestampMixin):
    """A single sales-material file (PDF/DOCX) attached to a client."""

    __tablename__ = "client_one_pagers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    uploaded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    client = relationship("Client", backref="one_pagers")
    uploader = relationship("User", foreign_keys=[uploaded_by])

    def __repr__(self) -> str:
        return (
            f"<ClientOnePager id={self.id} client={self.client_id} "
            f"title={self.title!r}>"
        )
