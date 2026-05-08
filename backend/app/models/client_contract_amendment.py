"""Aneks do umowy ramowej (MSA amendment) — zmiana stawek, off-limits, scope.

Każdy aneks to PDF (lub tylko opisowy diff) z `effective_date` i opcjonalnym
JSONB diff (``old_terms`` → ``new_terms``) który UI używa do podświetlenia
co się zmieniło bez czytania całego PDFa.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ClientContractAmendment(Base, TimestampMixin):
    """Aneks do `ClientFrameworkContract` — wersjonowana zmiana warunków."""

    __tablename__ = "client_contract_amendments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    framework_contract_id: Mapped[int] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    """Np. ``Aneks 1 — zmiana off-limits``."""

    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    changes_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Strukturalny diff (opcjonalny) — UI może podświetlić zmiany w polach
    # ClientContractTerms bez parsowania PDFa.
    old_terms: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    new_terms: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # File metadata
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

    # Relationships
    framework_contract = relationship(
        "ClientFrameworkContract", back_populates="amendments"
    )
    uploader = relationship("User", foreign_keys=[uploaded_by])

    def __repr__(self) -> str:
        return (
            f"<ClientContractAmendment id={self.id} "
            f"framework={self.framework_contract_id} "
            f"effective={self.effective_date}>"
        )
