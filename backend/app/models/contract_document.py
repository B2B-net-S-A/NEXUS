"""Contract document attachments (signed contract PDF, annexes, NIP, OC policy...)."""

import enum
from datetime import date
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ContractDocumentType(str, enum.Enum):
    contract = "contract"
    annex = "annex"
    nda = "nda"
    nip = "nip"
    zus_certificate = "zus_certificate"
    oc_policy = "oc_policy"
    order = "order"
    other = "other"


class ContractDocument(Base, TimestampMixin):
    """A single file uploaded against a contract (PDF, DOCX, etc.)."""

    __tablename__ = "contract_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    doc_type: Mapped[ContractDocumentType] = mapped_column(
        Enum(ContractDocumentType, name="contractdocumenttype"),
        default=ContractDocumentType.other,
        nullable=False,
        server_default="other",
    )

    # Dla dokumentów z terminem ważności (OC, NIP, ZUS zaświadczenie) — używane
    # przez C2 compliance tracking.
    expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    uploaded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Automatyczna kopia PDF zamówienia wielo-konsultantowego. NULL oznacza
    # dokument ręczny albo historyczny po usunięciu grupy (FK SET NULL).
    # Unikalność (contract_id, source_order_group_id) jest w migracji jako
    # indeks częściowy: podmiana PDF aktualizuje wiersz, nigdy nie dopisuje
    # duplikatu obok starego.
    source_order_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_order_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    contract = relationship("Contract", back_populates="documents_rel")

    def __repr__(self) -> str:
        return (
            f"<ContractDocument id={self.id} contract={self.contract_id} "
            f"type={self.doc_type} filename={self.filename!r}>"
        )
