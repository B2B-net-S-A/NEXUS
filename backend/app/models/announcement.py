"""„Ogłoszenia” na pulpicie (0617) — modele.

CHECK-i i indeksy muszą być identyczne z ``app/services/announcements_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import announcements_schema as schema


class Announcement(Base, TimestampMixin):
    __tablename__ = "announcements"
    __table_args__ = (
        CheckConstraint(schema.CK_AUDIENCE_SQL, name=schema.CK_AUDIENCE),
        CheckConstraint(schema.CK_TITLE_SQL, name=schema.CK_TITLE),
        Index(
            "ix_announcements_live",
            "visible_until",
            postgresql_where=text("withdrawn_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(schema.TITLE_MAX), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Ostatni dzień widoczności w kalendarzu firmy (Europe/Warsaw), włącznie.
    visible_until: Mapped[date] = mapped_column(Date, nullable=False)
    # Pusta lista = wszyscy; inaczej wartości `UserRole`.
    audience_roles: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    important: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    author_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Dzwonek i mail „ważnego” wychodzą raz (także gdy „ważne” dojdzie w edycji).
    notified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    withdrawn_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class AnnouncementRead(Base):
    __tablename__ = "announcement_reads"
    __table_args__ = (Index("ix_announcement_reads_user", "user_id"),)

    announcement_id: Mapped[int] = mapped_column(
        ForeignKey("announcements.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
