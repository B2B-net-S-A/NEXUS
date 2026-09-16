"""Aplikacje z portali (JJIT) już przetworzone przez job importu w NEXUS.

Zamiennik pliku ``scraper_state.json`` ze scrapera na Macu: jeden wiersz na
(źródło, ID aplikacji w portalu). Trzyma, gdzie kandydat wylądował
(NEXUS / Traffit), odcisk wgranego CV (żeby ten sam plik nie szedł drugi raz
do istniejącego kandydata) i ostatnią akcję — dzięki temu replay jest
idempotentny, a statystyki „ile aplikacji obsłużyliśmy" nie zależą od logów.
Migracja 0313.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class IntegrationExternalItem(Base):
    __tablename__ = "integration_external_items"
    __table_args__ = (
        UniqueConstraint("source", "external_id", name="uq_integration_external_items"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    traffit_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cv_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    offer_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_action: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["IntegrationExternalItem"]
