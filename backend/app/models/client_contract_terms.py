"""Structured MSA-level contract terms per client.

One row per client (UNIQUE(client_id)). Captures the key commercial
clauses — off-limits, internalization, payment, warranty — that the
sales/delivery team needs to recall quickly without re-reading the PDF.
"""

from decimal import Decimal
from typing import Optional

from sqlalchemy import ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ClientContractTerms(Base, TimestampMixin):
    __tablename__ = "client_contract_terms"
    __table_args__ = (
        UniqueConstraint("client_id", name="uq_client_contract_terms_client"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    # Off-limits
    off_limits_months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    off_limits_scope: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    off_limits_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Internalization (client hires contractor permanently)
    internalization_fee_pct: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    internalization_min_months: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    internalization_notice_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    internalization_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Payment terms
    payment_net_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payment_currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    payment_invoice_cycle: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True
    )
    payment_late_fees: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    payment_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Termination & warranty
    notice_period_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    warranty_replacement_days: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    warranty_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Free-text
    other_clauses: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    client = relationship("Client", backref="contract_terms", uselist=False)
    editor = relationship("User", foreign_keys=[updated_by])

    def __repr__(self) -> str:
        return f"<ClientContractTerms id={self.id} client={self.client_id}>"
