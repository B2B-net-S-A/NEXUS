"""Candidate Chat — internal team chat per candidate (Phase 2 of chat module).

Mirrors `job_chat.py` structure but scoped to a single candidate. Members:
    - admin
    - candidate.created_by (recruiter who added)
    - any user who is recruiter/DL/TAC of a Job that has this candidate in
      its pipeline (via candidate_stages)
    - any active job_collaborator on such Job

Use-case: rozmowa o konkretnym człowieku ("co z Kowalskim?") niezależna od
projektu — skraca path z chatu Job (gdzie kontekst jest mieszany) do
dedykowanego strumienia per kandydat.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class CandidateChatMessage(Base, TimestampMixin):
    """Wiadomość chatu zespołu o konkretnym kandydacie."""

    __tablename__ = "candidate_chat_messages"
    __table_args__ = (
        Index(
            "ix_candidate_chat_messages_candidate_created",
            "candidate_id",
            "created_at",
        ),
        Index(
            "ix_candidate_chat_messages_search",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_candidate_chat_messages_pinned",
            "candidate_id",
            "pinned_at",
            postgresql_where=text("pinned = true AND is_deleted = false"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)

    reply_to_message_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_chat_messages.id", ondelete="SET NULL"), nullable=True
    )

    is_edited: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    edited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False, index=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    pinned: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    pinned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pinned_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    external_platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    external_message_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    search_vector: Mapped[Optional[str]] = mapped_column(TSVECTOR, nullable=True)

    candidate = relationship("Candidate", back_populates="chat_messages")
    author = relationship("User", foreign_keys=[author_id])
    pinner = relationship("User", foreign_keys=[pinned_by])
    reply_to = relationship(
        "CandidateChatMessage",
        remote_side="CandidateChatMessage.id",
        foreign_keys=[reply_to_message_id],
    )
    mentions = relationship(
        "CandidateChatMention",
        back_populates="message",
        cascade="all, delete-orphan",
    )
    reactions = relationship(
        "CandidateChatMessageReaction",
        back_populates="message",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<CandidateChatMessage id={self.id} candidate={self.candidate_id} "
            f"author={self.author_id}>"
        )


class CandidateChatMention(Base):
    __tablename__ = "candidate_chat_mentions"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "user_id", name="uq_candidate_chat_mentions_msg_user"
        ),
        Index("ix_candidate_chat_mentions_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message = relationship("CandidateChatMessage", back_populates="mentions")
    user = relationship("User")


class CandidateChatReadState(Base):
    __tablename__ = "candidate_chat_read_state"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "user_id",
            name="uq_candidate_chat_read_state_candidate_user",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_read_message_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
