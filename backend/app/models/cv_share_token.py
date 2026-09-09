"""Token-based public link do brandowanego CV (per CandidateStage).

Rekruter generuje token po finalize brandowanego CV. Klient otwiera link
`/cv/{token}` w przeglądarce (bez logowania) i widzi tylko HTML CV +
podstawowe info (imię + tytuł oferty). Bez emaila, telefonu, nazwiska — to
jest hard-checkowane w `PublicCVView`.

TTL domyślnie 30 dni. Token można odwołać (`revoked=true`).

Mirror `EngagementDeclarationToken` (migracja 0062) i `ChampionCardShareToken`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.models.candidate_stage_cv import CandidateStageCV
    from app.models.user import User


class CVShareToken(Base):
    __tablename__ = "cv_share_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("cv_document_versions.id", ondelete="CASCADE"), nullable=True
    )
    candidate_stage_cv_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_stage_cvs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_by: Mapped[int] = mapped_column(
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

    # ── Token v2 (M4 audyt P1.9, migracja 0176) ─────────────────────────────
    # Nowe tokeny NIE przechowują sekretu: kolumna ``token`` (PK) dostaje
    # nie-sekretny identyfikator ``v2$<hex>``, a sekret istnieje wyłącznie
    # jako SHA-256 w ``token_sha256`` (raw pokazany użytkownikowi raz przy
    # utworzeniu). Legacy wiersze (raw w ``token``) działają w dual-read do
    # czasu wygaśnięcia/odwołania.
    token_sha256: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    max_views: Mapped[Optional[int]] = mapped_column(nullable=True)
    view_count: Mapped[int] = mapped_column(
        nullable=False, server_default="0", default=0
    )
    last_viewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    purpose: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    candidate_stage_cv: Mapped["CandidateStageCV"] = relationship(
        "CandidateStageCV", lazy="joined"
    )
    creator: Mapped[Optional["User"]] = relationship(
        "User", lazy="select", foreign_keys=[created_by]
    )
