"""Per-klient instancja wymaganego dokumentu (NDA klienta, RODO, off-limits, ...).

Każda instancja może być utworzona z szablonu (`template_id`) lub ad-hoc
(`template_id=NULL`). Plik (PDF/DOCX) trzymany poza DB przez storage_service.

Status:
- pending  — utworzony, plik nie wgrany
- uploaded — plik wgrany, ale brak potwierdzenia że podpisany
- signed   — komplet (plik wgrany + zatwierdzony)
- n_a      — klient nie wymaga (świadomy opt-out)
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ClientDocStatus(str, enum.Enum):
    pending = "pending"
    uploaded = "uploaded"
    signed = "signed"
    n_a = "n_a"


class ClientRequiredDocument(Base, TimestampMixin):
    """Per-klient instancja wymaganego dokumentu w procesie."""

    __tablename__ = "client_required_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("required_document_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    status: Mapped[ClientDocStatus] = mapped_column(
        Enum(ClientDocStatus, name="clientdocstatus", create_type=False),
        default=ClientDocStatus.pending,
        server_default="pending",
        nullable=False,
    )

    # File metadata — file_path-based storage (storage_service), spójne z ClientOnePager
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    uploaded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    client = relationship("Client", backref="required_documents")
    template = relationship("RequiredDocumentTemplate", foreign_keys=[template_id])
    uploader = relationship("User", foreign_keys=[uploaded_by])

    def __repr__(self) -> str:
        return (
            f"<ClientRequiredDocument id={self.id} client={self.client_id} "
            f"name={self.name!r} status={self.status}>"
        )
