"""Pamięć „Pomiń” propozycji struktury u klienta (migracja 0475).

Reguły i kontrakt tabeli: ``app/services/client_structure_schema.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import client_structure_schema as schema


class ClientStructureSkip(Base):
    """Pominięta propozycja: menedżer konsultanta albo przełożony osoby klienta."""

    __tablename__ = "client_structure_skips"
    __table_args__ = (
        CheckConstraint(schema.CK_SKIP_KIND, name="ck_client_structure_skips_kind"),
        CheckConstraint(
            schema.CK_SKIP_SUBJECT, name="ck_client_structure_skips_subject"
        ),
        Index("ix_client_structure_skips_client", "client_id"),
        Index(
            "uq_client_structure_skips_contract",
            "contract_id",
            unique=True,
            postgresql_where=text("kind = 'manager'"),
        ),
        Index(
            "uq_client_structure_skips_contact",
            "contact_id",
            unique=True,
            postgresql_where=text("kind = 'reports_to'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True
    )
    contact_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True
    )
    proposed_contact_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contacts.id", ondelete="CASCADE"), nullable=True
    )
    skipped_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    skipped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
