"""Teams meetings and candidate-owned transcripts for follow-up conversations."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FollowupMeeting(Base):
    __tablename__ = "followup_meetings"
    __table_args__ = (
        Index("ix_followup_meetings_candidate", "candidate_id", "created_at"),
        Index("ix_followup_meetings_queue", "transcript_status", "next_fetch_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    calendar_event_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("calendar_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    organizer_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    organizer_upn: Mapped[str] = mapped_column(String(320), nullable=False)
    organizer_aad_id: Mapped[Optional[str]] = mapped_column(String(64))
    online_meeting_id: Mapped[Optional[str]] = mapped_column(String(512))
    client_request_id: Mapped[str] = mapped_column(
        String(80), nullable=False, unique=True
    )
    transcription_setup: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    transcript_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="waiting"
    )
    fetch_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    next_fetch_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(String(120))
    transcript_vtt: Mapped[Optional[str]] = mapped_column(Text)
    transcript_text: Mapped[Optional[str]] = mapped_column(Text)
    transcript_fetched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
