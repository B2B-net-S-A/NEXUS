import enum
from typing import Optional

from sqlalchemy import Enum, ForeignKey, Integer, Text
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

    def __repr__(self) -> str:
        return (
            f"<Note id={self.id} type={self.note_type} candidate={self.candidate_id}>"
        )
