"""Powiązanie dwóch haseł słownika umiejętności (0660, 07.11.2026).

Mapa wiedzy IT: „wynika z” (Spring Boot ⇒ Java), „część” (GitHub ⇒ Git),
„zamiennik” (Flask ~ FastAPI) i „typowe” (Java ⇒ Maven). Twarde rodzaje
spełniają wymaganie wszędzie, miękkie dają pytanie do rozmowy. Działa tylko
powiązanie zatwierdzone w „Słowniku umiejętności”. DDL:
``app/services/skill_relations_schema.py``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SkillRelation(Base):
    __tablename__ = "skill_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    from_skill_id: Mapped[int] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    to_skill_id: Mapped[int] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="proposed")
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="data")
    # Ilu profili z hasłem „od” i jaki ich odsetek wpisuje też „do”.
    support: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    share: Mapped[Optional[Decimal]] = mapped_column(Numeric(5, 4), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    curated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    curated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
