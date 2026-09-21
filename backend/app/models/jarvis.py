"""Jarvis — rozmowy, proponowane akcje i powiązania z rekordami (0330).

Jarvis nie ma własnych uprawnień: każde narzędzie woła istniejące API tokenem
pytającego (``app/services/jarvis/transport.py``). Te tabele trzymają wyłącznie
stan rozmowy:

- ``jarvis_conversations`` — rozmowa jednej osoby. ``busy_until`` to blokada
  „jedna tura naraz”: druga wiadomość w trakcie trwającej tury dostaje 409,
  a przeterminowana blokada (proces zabity deployem) nie wisi wiecznie.
- ``jarvis_messages`` — historia w kształcie bloków Anthropic (``text``,
  ``tool_use``, ``tool_result``), bo tę samą listę pętla odsyła modelowi.
- ``jarvis_actions`` — zapis PROPONOWANY przez model. Wykonuje go dopiero
  kliknięcie człowieka (``POST /api/jarvis/actions/{id}/confirm``), i to
  DOKŁADNIE z zapisanymi tu ``args`` — model nie może ich podmienić po pokazaniu
  karty.
- ``jarvis_conversation_entities`` — które rekordy padły w rozmowie. Po nich
  usunięcie kandydata (art. 17 RODO) znajduje i kasuje rozmowy z jego danymi:
  treść rozmowy to JSON, więc zwykła kaskada FK by do niej nie sięgnęła.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

JARVIS_MESSAGE_ROLES = ("user", "assistant")
JARVIS_ACTION_STATUSES = (
    "proposed",
    "confirmed",
    "rejected",
    "executed",
    "failed",
    "expired",
)


class JarvisConversation(Base):
    __tablename__ = "jarvis_conversations"
    __table_args__ = (
        Index("ix_jarvis_conversations_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        default="Nowa rozmowa",
        server_default="Nowa rozmowa",
    )
    last_context: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    busy_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JarvisMessage(Base):
    __tablename__ = "jarvis_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_jarvis_messages_role"
        ),
        Index("ix_jarvis_messages_conversation", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jarvis_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # Lista bloków Anthropic — dokładnie to, co pętla odsyła modelowi.
    content: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JarvisAction(Base):
    __tablename__ = "jarvis_actions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'confirmed', 'rejected', 'executed', 'failed', 'expired')",
            name="ck_jarvis_actions_status",
        ),
        Index("ix_jarvis_actions_conversation", "conversation_id"),
        Index("ix_jarvis_actions_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jarvis_conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tool_use_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(64), nullable=False)
    args: Mapped[dict] = mapped_column(JSONB, nullable=False)
    preview: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="proposed", server_default="proposed"
    )
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class JarvisConversationEntity(Base):
    __tablename__ = "jarvis_conversation_entities"
    __table_args__ = (
        Index("ix_jarvis_conversation_entities_entity", "entity_type", "entity_id"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jarvis_conversations.id", ondelete="CASCADE"),
        primary_key=True,
    )
    entity_type: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity_id: Mapped[int] = mapped_column(Integer, primary_key=True)
