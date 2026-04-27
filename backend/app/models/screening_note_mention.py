from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ScreeningNoteMention(Base):
    """Flat lista @mention'ów per ScreeningNote."""

    __tablename__ = "screening_note_mentions"
    __table_args__ = (
        UniqueConstraint(
            "screening_note_id",
            "user_id",
            name="uq_screening_note_mentions_note_user",
        ),
        Index("ix_screening_note_mentions_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    screening_note_id: Mapped[int] = mapped_column(
        ForeignKey("screening_notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    screening_note = relationship("ScreeningNote", back_populates="mentions")
    user = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<ScreeningNoteMention note={self.screening_note_id} "
            f"user={self.user_id}>"
        )
