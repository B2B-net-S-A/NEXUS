"""Fragment tekstu dokumentu kontraktu — 0782.

Opis: ``app/services/contract_document_text/schema.py``. Zapis i odczyt:
``app/services/contract_document_text/index.py``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ContractDocumentChunk(Base):
    __tablename__ = "contract_document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "contract_document_id",
            "chunk_index",
            name="uq_contract_document_chunks_position",
        ),
        Index("ix_contract_document_chunks_contract", "contract_id"),
    )

    # Identyfikator punktu w kolekcji Qdranta ``nexus_contract_documents``.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    contract_document_id: Mapped[int] = mapped_column(
        ForeignKey("contract_documents.id", ondelete="CASCADE"), nullable=False
    )
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
