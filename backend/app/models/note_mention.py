from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class NoteMention(Base):
    """Flat lista @mention'ów per Note — dla inboxa "moje mentions"."""

    __tablename__ = "note_mentions"
    __table_args__ = (
        UniqueConstraint("note_id", "user_id", name="uq_note_mentions_note_user"),
        Index("ix_note_mentions_user_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    note_id: Mapped[int] = mapped_column(
        ForeignKey("notes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    note = relationship("Note", back_populates="mentions")
    user = relationship("User")

    def __repr__(self) -> str:
        return f"<NoteMention note={self.note_id} user={self.user_id}>"
