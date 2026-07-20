"""Champion Card share tokens (Phase 12).

A recruiter can generate a shareable link (random URL-safe token) that lets an
external client view the filled Champion card without authenticating against
the ATS. The public endpoint honours `expires_at` and the `revoked` flag.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChampionCardShareToken(Base):
    __tablename__ = "champion_card_share_tokens"

    token: Mapped[str] = mapped_column(Text, primary_key=True)
    candidate_stage_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_stages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False
    )

    # ── Token v2 (hash-at-rest, migracja 0181) ──────────────────────────────
    # Ten sam wzorzec co CVShareToken (0176): nowe tokeny NIE trzymają sekretu.
    # Kolumna ``token`` (PK) dostaje nie-sekretny identyfikator ``v2$<hex>``,
    # a sekret istnieje wyłącznie jako SHA-256 w ``token_sha256`` — raw pokazany
    # raz przy utworzeniu i przenoszony w URL. Legacy wiersze (raw w ``token``,
    # token_sha256 IS NULL) działają w dual-read do wygaśnięcia/odwołania.
    # Powód: gołe plaintextowe PK znaczyło, że wyciek DB = gotowa lista
    # działających linków do kart champion (PII kandydata + odpowiedzi
    # screeningowe).
    token_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
