"""Job Chat — internal team chat per recruitment.

Each Job has a dedicated chat stream. Members are: job.recruiter_id,
job.delivery_lead_id, all rows in job_collaborators where
removed_from_auto_cc=false, and any user with role=admin. Clients and
candidates have no access — this is a back-office only feature.

Three tables:
    job_chat_messages   — the messages themselves (soft-delete + FTS)
    job_chat_mentions   — flat denormalized @mention list (per msg+user)
    job_chat_read_state — per-user-per-job last_read pointer for unread badge
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


class JobChatMessage(Base, TimestampMixin):
    """Pojedyncza wiadomość wewnętrznego czatu zespołu per projekt (Job).

    - `is_deleted=True` zachowuje wiersz (audit) ale UI pokazuje placeholder.
    - `pinned` ograniczone do 3 wiad. per job (sprawdzane na warstwie API).
    - `search_vector` aktualizowany triggerem PG (zob. migracja 0061).
    - `external_*` zarezerwowane na Teams/Slack 2-way sync (v2).
    """

    __tablename__ = "job_chat_messages"
    __table_args__ = (
        Index("ix_job_chat_messages_job_created", "job_id", "created_at"),
        Index(
            "ix_job_chat_messages_search",
            "search_vector",
            postgresql_using="gin",
        ),
        Index(
            "ix_job_chat_messages_pinned",
            "job_id",
            "pinned_at",
            postgresql_where=text("pinned = true AND is_deleted = false"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    content: Mapped[str] = mapped_column(Text, nullable=False)

    reply_to_message_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_chat_messages.id", ondelete="SET NULL"), nullable=True
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

    # Reserved for future Teams/Slack 2-way sync (v2).
    external_platform: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    external_message_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )

    # Postgres FTS — populated by trigger (see migration 0061).
    search_vector: Mapped[Optional[str]] = mapped_column(TSVECTOR, nullable=True)

    # Relationships
    job = relationship("Job", back_populates="chat_messages")
    author = relationship("User", foreign_keys=[author_id])
    pinner = relationship("User", foreign_keys=[pinned_by])
    reply_to = relationship(
        "JobChatMessage", remote_side="JobChatMessage.id", foreign_keys=[reply_to_message_id]
    )
    mentions = relationship(
        "JobChatMention", back_populates="message", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<JobChatMessage id={self.id} job={self.job_id} "
            f"author={self.author_id} deleted={self.is_deleted}>"
        )


class JobChatMention(Base):
    """Flat lista @mention'ów per wiadomość — ułatwia inbox 'moje mentions'."""

    __tablename__ = "job_chat_mentions"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "user_id", name="uq_job_chat_mentions_msg_user"
        ),
        Index("ix_job_chat_mentions_user", "user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("job_chat_messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message = relationship("JobChatMessage", back_populates="mentions")
    user = relationship("User")

    def __repr__(self) -> str:
        return f"<JobChatMention msg={self.message_id} user={self.user_id}>"


class JobChatReadState(Base):
    """Per-user-per-job: ostatnia przeczytana wiadomość → unread badge."""

    __tablename__ = "job_chat_read_state"
    __table_args__ = (
        UniqueConstraint(
            "job_id", "user_id", name="uq_job_chat_read_state_job_user"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    last_read_message_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_chat_messages.id", ondelete="SET NULL"), nullable=True
    )
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<JobChatReadState job={self.job_id} user={self.user_id} "
            f"last_read={self.last_read_message_id}>"
        )
