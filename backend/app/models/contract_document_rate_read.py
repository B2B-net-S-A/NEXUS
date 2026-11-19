"""Odczyt stawki Partnera z pliku w Dokumentach kontraktu (0739).

Wiersz = jeden plik i wersja czytnika. ``result`` to propozycja modelu (kroki
stawki z datami, cytat), ``finding`` — różnica z harmonogramem
``contract_candidate_rates`` policzona przez kod
(``services/contract_rate_documents/compare.py``), ``decision`` — co zrobił
człowiek albo wpis automatyczny. DDL: ``services/contract_rate_documents/schema_sql.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ContractDocumentRateRead(Base):
    __tablename__ = "contract_document_rate_reads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_document_id: Mapped[int] = mapped_column(
        ForeignKey("contract_documents.id", ondelete="CASCADE"), nullable=False
    )
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reader_version: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    finding: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    has_finding: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    decision: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    decision_amendment_ids: Mapped[Optional[list[int]]] = mapped_column(
        JSONB, nullable=True
    )
    decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
