"""Dokumenty dodatków do rozliczenia kontraktora (0690). Sam dodatek
(``ClientSettlementExtra``) jest w ``app/models/client_settlement.py``.

CHECK-i i indeksy jak w ``app/services/client_settlement_extras_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.client_settlement import ClientSettlementExtra
from app.services import client_settlement_extras_schema as schema

__all__ = ["ClientSettlementExtra", "ClientSettlementExtraDocument"]


class ClientSettlementExtraDocument(Base):
    __tablename__ = "client_settlement_extra_documents"
    __table_args__ = (
        UniqueConstraint(
            "extra_id", "sha256", name="uq_client_settlement_extra_documents_file"
        ),
        CheckConstraint(
            schema.CK_DOC_CHANNEL, name="ck_client_settlement_extra_documents_channel"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    extra_id: Mapped[int] = mapped_column(
        ForeignKey("client_settlement_extras.id", ondelete="CASCADE"), nullable=False
    )
    file_path: Mapped[str] = mapped_column(String(300), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(
        String(schema.FILE_NAME_MAX), nullable=True
    )
    mime: Mapped[str] = mapped_column(String(120), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(8), nullable=False)
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
