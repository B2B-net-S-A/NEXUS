import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class NoteType(str, enum.Enum):
    call = "call"
    meeting = "meeting"
    email = "email"
    general = "general"
    interview = "interview"


class Note(Base, TimestampMixin):
    """
    Notatka powiązana z kandydatem i/lub ofertą pracy.
    """

    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    content: Mapped[str] = mapped_column(Text, nullable=False)
    note_type: Mapped[NoteType] = mapped_column(
        Enum(NoteType), default=NoteType.general, nullable=False
    )

    # Powiązania — notatka może być przy kandydacie, ofercie, kontrakcie lub
    # ich kombinacji. Wszystkie FK są nullable + ON DELETE SET NULL.
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id"), index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), index=True)
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    author_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    # Zewnętrzne pochodzenie notatki (np. "fireflies:<transcript_id>") —
    # dedup przy re-syncu + lookup audio dla briefingu DL.
    source_ref: Mapped[Optional[str]] = mapped_column(String(120), index=True)
    # Structured source identity. `source_ref` remains for backwards
    # compatibility and human-readable audit links.
    external_source: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    source_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    source_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    source_deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    # Traffit notes are append-only. An edit creates a marked correction that
    # points at the superseded local note instead of mutating remote history.
    supersedes_note_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    # Link do nagrania (Fireflies CDN). Może wygasać — briefing kopiuje
    # audio do Object Storage zamiast polegać na tym URL-u.
    audio_url: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    candidate = relationship("Candidate", back_populates="notes")
    job = relationship("Job", back_populates="notes")
    contract = relationship(
        "Contract", back_populates="contract_notes", foreign_keys=[contract_id]
    )
    author = relationship(
        "User", back_populates="authored_notes", foreign_keys=[author_id]
    )
    mentions = relationship(
        "NoteMention",
        back_populates="note",
        cascade="all, delete-orphan",
    )
    supersedes_note = relationship(
        "Note", remote_side=[id], foreign_keys=[supersedes_note_id]
    )

    __table_args__ = (
        Index(
            "ux_notes_external_source_id",
            "external_source",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index(
            "ix_notes_candidate_source_created",
            "candidate_id",
            "external_source",
            "source_created_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Note id={self.id} type={self.note_type} candidate={self.candidate_id}>"
        )
