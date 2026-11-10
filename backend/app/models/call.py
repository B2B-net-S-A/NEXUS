import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class CallDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class CallStatus(str, enum.Enum):
    completed = "completed"
    missed = "missed"
    voicemail = "voicemail"
    failed = "failed"
    initiated = "initiated"  # outbound stub before call-ended webhook arrives


class Call(Base, TimestampMixin):
    """Rejestr rozmów telefonicznych z kandydatami.

    Rozmowy dopisuje ręcznie ``POST /api/calls``. Integracja telefonii
    usunięta 08.11.2026, jej kolumny zdjęte migracją 0681; wiersze zostają.
    """

    __tablename__ = "calls"
    __table_args__ = (
        CheckConstraint(
            "contact_outcome IS NULL OR contact_outcome IN "
            "('connected', 'no_answer', 'callback_requested', "
            "'wrong_number', 'do_not_contact')",
            name="ck_calls_contact_outcome",
        ),
        Index(
            "ux_calls_contact_idempotency_key",
            "contact_idempotency_key",
            unique=True,
            postgresql_where=text("contact_idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Powiązania
    # Nullable: historycznie rozmowa przychodząca, której numer pasował do
    # kilku kandydatów, zostawała nieprzypisana zamiast trafić do przypadkowej
    # osoby (F-12).
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=True, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Optional link to a contract — set when the call was about an active angaż.
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    contact_case_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_contact_cases.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Dane rozmowy
    direction: Mapped[CallDirection] = mapped_column(
        Enum(CallDirection), nullable=False, default=CallDirection.outbound
    )
    duration_seconds: Mapped[Optional[int]] = mapped_column(
        Integer
    )  # czas trwania w sekundach
    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus), nullable=False, default=CallStatus.completed, index=True
    )

    # Transkrypcja i podsumowanie (opcjonalne)
    transcript: Mapped[Optional[str]] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(Text)

    # URL nagrania
    recording_url: Mapped[Optional[str]] = mapped_column(String(1000))

    # Faktyczny początek rozmowy; ``created_at`` to chwila zapisu wiersza.
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Candidate-contact coordination metadata. Existing manual rows
    # stay NULL and retain their historical semantics.
    contact_outcome: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    contact_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    contact_idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(160), nullable=True
    )
    contact_request_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    callback_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    candidate = relationship("Candidate", back_populates="calls")
    user = relationship("User", foreign_keys=[user_id])
    contract = relationship(
        "Contract", back_populates="contract_calls", foreign_keys=[contract_id]
    )
    contact_case = relationship("CandidateContactCase", back_populates="calls")

    def __repr__(self) -> str:
        return f"<Call id={self.id} candidate_id={self.candidate_id} direction={self.direction} status={self.status}>"
