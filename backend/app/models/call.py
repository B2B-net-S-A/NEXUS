import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
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

    Inbound rows arrive via the CloudTalk webhook; outbound rows are stubbed
    by :func:`POST /api/cloudtalk/initiate-call` and then enriched by the
    webhook once the call ends.
    """

    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Powiązania
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Optional link to a contract — set when the call was about an active angaż.
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True, index=True
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

    # Transkrypcja i podsumowanie (opcjonalne, może przyjść z CloudTalk AI)
    transcript: Mapped[Optional[str]] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(Text)

    # URL nagrania (z CloudTalk)
    recording_url: Mapped[Optional[str]] = mapped_column(String(1000))

    # ID rozmowy w CloudTalk (do deduplikacji webhooków)
    cloudtalk_call_id: Mapped[Optional[str]] = mapped_column(
        String(255), unique=True, nullable=True, index=True
    )

    # CloudTalk agent identifier — denormalized so historical rows survive
    # rebindings of User → cloudtalk_agent_id. Set from webhook payload's
    # ``agent.id`` (Phase 2).
    cloudtalk_agent_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, index=True
    )

    # Exact start time as reported by CloudTalk. Distinct from ``created_at``
    # (which is when our row was inserted; the webhook may arrive minutes
    # after the call actually started).
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Relationships
    candidate = relationship("Candidate", back_populates="calls")
    user = relationship("User", foreign_keys=[user_id])
    contract = relationship(
        "Contract", back_populates="contract_calls", foreign_keys=[contract_id]
    )

    def __repr__(self) -> str:
        return f"<Call id={self.id} candidate_id={self.candidate_id} direction={self.direction} status={self.status}>"
