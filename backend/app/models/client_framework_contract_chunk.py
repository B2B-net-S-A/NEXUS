"""Fragment tekstu umowy ramowej klienta — 0426.

Opis: ``app/services/framework_contract_text_schema.py``. Zapis i odczyt:
``app/services/framework_contract_index.py``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientFrameworkContractChunk(Base):
    __tablename__ = "client_framework_contract_chunks"
    __table_args__ = (
        UniqueConstraint(
            "framework_contract_id",
            "chunk_index",
            name="uq_client_framework_contract_chunks_position",
        ),
    )

    # Identyfikator punktu w kolekcji Qdranta ``nexus_client_documents``.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    framework_contract_id: Mapped[int] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
