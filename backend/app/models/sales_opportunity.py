import enum
from typing import Optional
from datetime import datetime, date

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SalesStage(str, enum.Enum):
    lead = "lead"
    qualification = "qualification"
    proposal = "proposal"
    negotiation = "negotiation"
    won = "won"
    lost = "lost"


class SalesOpportunity(Base):
    """Szansa sprzedażowa — pipeline CRM."""
    __tablename__ = "sales_opportunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False, index=True)
    contact_person: Mapped[Optional[str]] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    stage: Mapped[SalesStage] = mapped_column(
        Enum(SalesStage), nullable=False, default=SalesStage.lead, index=True
    )

    value: Mapped[Optional[float]] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(10), default="PLN", nullable=False)
    probability: Mapped[int] = mapped_column(Integer, default=50, nullable=False)  # 0-100

    expected_close_date: Mapped[Optional[date]] = mapped_column(Date)
    assigned_to: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)

    lost_reason: Mapped[Optional[str]] = mapped_column(Text)
    converted_job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    client = relationship("Client", backref="sales_opportunities")
    assignee = relationship("User", foreign_keys=[assigned_to])
    converted_job = relationship("Job", foreign_keys=[converted_job_id])

    def __repr__(self) -> str:
        return f"<SalesOpportunity id={self.id} title={self.title} stage={self.stage}>"
