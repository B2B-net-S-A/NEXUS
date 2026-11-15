"""Zespół dla klienta (0711, gotowe składy 0712) — ``services/job_team_schema.py``."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobTeam(Base):
    __tablename__ = "job_teams"
    __table_args__ = (
        Index(
            "uq_job_teams_panel_token",
            "panel_token_sha256",
            unique=True,
            postgresql_where=text("panel_token_sha256 IS NOT NULL"),
        ),
        Index("ix_job_teams_client_id", "client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    panel_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    panel_show_rate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    panel_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    # Jak w panelu rekrutacji: token liczy się z sekretu aplikacji i tej
    # wartości, w bazie jest tylko skrót. Zmiana wartości = „Odwołaj link”.
    panel_token_nonce: Mapped[Optional[str]] = mapped_column(String(32))
    panel_token_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    # 0712: gotowe składy zatwierdzone przez DL-a, jedyne, które widzi klient.
    # ``[{"key", "name", "why", "picks": [{"job_id", "candidate_ids"}]}]``
    variants: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    variants_approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    variants_approved_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class JobTeamSelection(Base):
    __tablename__ = "job_team_selections"
    __table_args__ = (
        Index("ix_job_team_selections_team_created", "team_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    team_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("job_teams.id", ondelete="CASCADE"), nullable=False
    )
    # ``[{"job_id": 1, "candidate_ids": [2, 3]}]``
    picks: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # Imię i adres wpisane przez autora, niezweryfikowane.
    author_name: Mapped[str] = mapped_column(String(120), nullable=False)
    author_email: Mapped[str] = mapped_column(String(255), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(2000))
    # SHA-256 z IP i soli dnia; surowe IP nie trafia do bazy.
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
