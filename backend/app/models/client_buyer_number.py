"""Dodatkowy numer nabywcy klienta (0781): spółka grupy z własnym NIP-em albo VAT UE.

Główny numer zostaje w ``clients.nip``; ten wiersz to kolejny numer tego samego
klienta dla dopasowania faktur z KSeF (``client_invoicing.clients.nip_registry``).
Numer w postaci ``normalize_buyer_number``, jeden klient na numer (UNIQUE).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientBuyerNumber(Base):
    __tablename__ = "client_buyer_numbers"
    __table_args__ = (
        CheckConstraint(
            "source IN ('manual', 'auto')", name="ck_client_buyer_numbers_source"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    #: ``manual`` — Finanse w „Nieznani nabywcy” / oknie faktury; ``auto`` — automat.
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )
    added_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
