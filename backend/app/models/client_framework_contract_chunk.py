"""Fragment tekstu umowy ramowej klienta — 0426.

Opis: ``app/services/framework_contract_text_schema.py``. Zapis i odczyt:
``app/services/framework_contract_index.py``.
"""

from __future__ import annotations

from datetime import datetime

from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    func,
    text as sql_text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientFrameworkContractChunk(Base):
    __tablename__ = "client_framework_contract_chunks"
    __table_args__ = (
        Index(
            "ux_client_framework_contract_chunks_contract",
            "framework_contract_id",
            "chunk_index",
            unique=True,
            postgresql_where=sql_text("amendment_id IS NULL"),
            sqlite_where=sql_text("amendment_id IS NULL"),
        ),
        Index(
            "ux_client_framework_contract_chunks_amendment",
            "amendment_id",
            "chunk_index",
            unique=True,
            postgresql_where=sql_text("amendment_id IS NOT NULL"),
            sqlite_where=sql_text("amendment_id IS NOT NULL"),
        ),
    )

    # Identyfikator punktu w kolekcji Qdranta ``nexus_client_documents``.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    framework_contract_id: Mapped[int] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # NULL = tekst samej umowy, wartość = fragment jej aneksu (0627).
    amendment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_contract_amendments.id", ondelete="CASCADE"),
        nullable=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
