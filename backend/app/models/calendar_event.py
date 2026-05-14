import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class EventType(str, enum.Enum):
    interview = "interview"
    screening = "screening"
    prep_call = "prep_call"
    meeting = "meeting"
    deadline = "deadline"


class EventStatus(str, enum.Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"


class CalendarEvent(Base, TimestampMixin):
    """
    Wydarzenie w kalendarzu rekrutacyjnym.
    Może być powiązane z kandydatem, ofertą lub klientem.
    """

    __tablename__ = "calendar_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, name="eventtype"), nullable=False, default=EventType.meeting
    )

    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Optional relations
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id"), index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), index=True)
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id"), index=True
    )

    # Attendees — list of emails
    attendees: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)

    location: Mapped[Optional[str]] = mapped_column(String(500))
    teams_link: Mapped[Optional[str]] = mapped_column(String(1000))

    # Phase 7b.6 — external calendar sources (iCal / Outlook / Google)
    external_id: Mapped[Optional[str]] = mapped_column(String(200), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )

    # Phase M365.1 — Microsoft Graph specifics (recurring series link + etag).
    m365_series_master_id: Mapped[Optional[str]] = mapped_column(
        String(255), index=True
    )
    m365_change_key: Mapped[Optional[str]] = mapped_column(String(100))

    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    reminder_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)

    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, name="eventstatus"),
        default=EventStatus.scheduled,
        nullable=False,
        index=True,
    )

    # Phase 14 — flagowany gdy T+2h eskalacja bez feedbacku; czyszczony po zapisie.
    needs_attention: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    # Phase 7.5 — candidate self-confirmation (Outlook Actionable Messages or
    # fallback paths). NULL until the candidate clicks "Potwierdzam" in the
    # email; then populated with the confirmation timestamp + source string
    # (`outlook_actionable`, `manual_email_reply`, `phone`).
    candidate_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    candidate_confirmation_source: Mapped[Optional[str]] = mapped_column(String(50))

    # Relationships
    candidate = relationship("Candidate", foreign_keys=[candidate_id])
    job = relationship("Job", foreign_keys=[job_id])
    client = relationship("Client", foreign_keys=[client_id])
    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return (
            f"<CalendarEvent id={self.id} title={self.title!r} type={self.event_type}>"
        )
