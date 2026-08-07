"""Publiczny link do WYGENEROWANEGO CV (Generator B2B) + chat hiring managera.

Tożsamy wzorzec bezpieczeństwa co ``CVShareToken`` (brandowane CV per stage,
migracja 0176 „token v2"), ale od pierwszego dnia WYŁĄCZNIE hash-at-rest:

* sekret = ``secrets.token_urlsafe(36)``, pokazany rekruterowi raz, żyje tylko
  w URL ``/cv/i/{token}``;
* kolumna ``token`` (PK) dostaje nie-sekretny revoke-key ``v2$<hex>``;
* w DB ląduje tylko ``token_sha256`` — brak gałęzi legacy/dual-read.

Link prowadzi do strony z dwoma widokami: „classic" (HTML 1:1 z
``render_payload``) i „interaktywnym" (kafelki wymagań + chat). Kafelki i chat
są dostępne tylko dla CV z trybu „new" (jest job → są wymagania) i tylko gdy
klient ma włączone ``Client.cv_interactive_enabled``.

``CvShareChatMessage`` przechowuje pytania managera i odpowiedzi AI — po
pierwsze jako dzienny limit anty-kosztowy per link, po drugie jako sygnał
sprzedażowy (co managerowie realnie sprawdzają przed decyzją).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.models.cv_generated_document import CvGeneratedDocument
    from app.models.user import User


class CvGeneratedShareToken(Base):
    __tablename__ = "cv_generated_share_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    generated_document_id: Mapped[int] = mapped_column(
        ForeignKey("cv_generated_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false", default=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    max_views: Mapped[Optional[int]] = mapped_column(nullable=True)
    view_count: Mapped[int] = mapped_column(
        nullable=False, server_default="0", default=0
    )
    last_viewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    generated_document: Mapped["CvGeneratedDocument"] = relationship(
        "CvGeneratedDocument", lazy="joined"
    )
    creator: Mapped[Optional["User"]] = relationship(
        "User", lazy="select", foreign_keys=[created_by]
    )


class CvShareChatMessage(Base):
    """Jedna wiadomość chatu na publicznym linku CV (pytanie LUB odpowiedź).

    Klucz obcy wskazuje na REVOKE-KEY tokenu (PK ``cv_generated_share_tokens``),
    nigdy na sekret — sekret nie istnieje w DB. Dzienny limit pytań liczony
    jest per link: ``COUNT(*) WHERE role='user' AND created_at >= start dnia``.
    """

    __tablename__ = "cv_share_chat_messages"
    __table_args__ = (
        # Dzienny licznik pytań + odczyt historii idą po (token, created_at).
        Index("ix_cv_share_chat_token_created", "share_token", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    share_token: Mapped[str] = mapped_column(
        ForeignKey("cv_generated_share_tokens.token", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
