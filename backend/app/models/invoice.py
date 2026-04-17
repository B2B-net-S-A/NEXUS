"""Invoice tracking — light ledger, no generation."""

import enum
from datetime import date
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class InvoiceDirection(str, enum.Enum):
    to_client = "to_client"  # agencja → klient
    from_contractor = "from_contractor"  # kontraktor → agencja (B2B)


class InvoiceStatus(str, enum.Enum):
    issued = "issued"
    sent = "sent"
    paid = "paid"
    overdue = "overdue"
    cancelled = "cancelled"


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    direction: Mapped[InvoiceDirection] = mapped_column(
        Enum(InvoiceDirection, name="invoicedirection"), nullable=False
    )
    invoice_number: Mapped[str] = mapped_column(String(64), nullable=False)
    period_month: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    period_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    paid_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="PLN", nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        Enum(InvoiceStatus, name="invoicestatus"),
        default=InvoiceStatus.issued,
        nullable=False,
        index=True,
    )
    pdf_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contract_documents.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    contract = relationship("Contract", back_populates="invoices")

    def __repr__(self) -> str:
        return (
            f"<Invoice id={self.id} contract={self.contract_id} "
            f"number={self.invoice_number!r} status={self.status}>"
        )
