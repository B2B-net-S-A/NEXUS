"""Dane firmy Partnera odczytane z pliku umowy kontraktu (E5a, 0755).

Wiersz = jeden plik umowy i wersja czytnika. ``result`` to propozycja modelu
(pola firmy z cytatami i uwagi kodu, np. zła cyfra kontrolna NIP-u),
``verification`` — wynik sprawdzenia w CEIDG albo KRS na żądanie człowieka,
``decision`` — „Zastosuj” albo „Odrzuć”. ``confirmed`` to dane potwierdzone
przez człowieka (z poprawkami), ``candidate_changes`` — co trafiło do profilu
kandydata. DDL: ``services/contract_partner_reads/schema_sql.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ContractPartnerRead(Base):
    __tablename__ = "contract_partner_reads"

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
    verification: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    confirmed: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    candidate_changes: Mapped[Optional[dict[str, Any]]] = mapped_column(
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
