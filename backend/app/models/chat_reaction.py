"""Emoji reactions on chat messages — both job and candidate variants.

Two parallel tables (one per chat type) instead of polymorphic single table:
    - simpler FK + cascade semantics
    - no GIN-style entity_type filtering needed
    - matches existing pattern (job_chat_mentions vs candidate_chat_mentions)

Each row = one user reacted with one emoji to one message. UNIQUE constraint
on (message_id, user_id, emoji) prevents duplicate reactions.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class JobChatMessageReaction(Base):
    """Emoji reaction on a JobChatMessage."""

    __tablename__ = "job_chat_message_reactions"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "user_id",
            "emoji",
            name="uq_job_chat_msg_reaction",
        ),
        Index("ix_job_chat_msg_reactions_message", "message_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("job_chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Emoji as Unicode string (e.g. "👍", "❤️", "🚀"). Max 16 chars handles ZWJ
    # sequences and skin-tone modifiers.
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message = relationship("JobChatMessage", back_populates="reactions")
    user = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<JobChatMessageReaction msg={self.message_id} "
            f"user={self.user_id} emoji={self.emoji}>"
        )


class CandidateChatMessageReaction(Base):
    """Emoji reaction on a CandidateChatMessage."""

    __tablename__ = "candidate_chat_message_reactions"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "user_id",
            "emoji",
            name="uq_candidate_chat_msg_reaction",
        ),
        Index("ix_candidate_chat_msg_reactions_message", "message_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    emoji: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message = relationship("CandidateChatMessage", back_populates="reactions")
    user = relationship("User")
