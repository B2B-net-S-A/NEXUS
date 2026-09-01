"""Dziennik obserwacji poziomu seniority (append-only).

Pełne uzasadnienie — łącznie z tym, dlaczego wiersz powstaje TYLKO przy
zmianie i dlaczego odcisk progów leży na wierszu — siedzi w
`app/services/insights_seniority_journal.py`. Nie powielam go tutaj, żeby dwie
kopie nie rozjechały się przy pierwszej zmianie.

Model istnieje głównie po to, żeby tabela miała sondę w `/api/health/deep`:
`/api/insights/recruitment/seniority` czyta dziennik BEZWARUNKOWO przy każdym wejściu na
zakładkę, więc brak tabeli na prodzie (alembic bywa tam osierocony) wywala
całą sekcję Ścieżki rozwoju, a nie tylko ostrzeżenie o regresji. Zapisy i
odczyty idą surowym SQL-em w warstwie serwisu.
"""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InsightsSenioritySnapshot(Base):
    __tablename__ = "insights_seniority_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    # NULL = pierwsza obserwacja tej osoby, świadomie różne od „poziom bez
    # zmian": pierwszy wiersz nie jest zmianą i nie może się liczyć jako awans.
    previous_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    total_placements: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_total_placements: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    senior_since: Mapped[str | None] = mapped_column(String(7), nullable=True)
    expert_since: Mapped[str | None] = mapped_column(String(7), nullable=True)
    thresholds_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    is_regression: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    __table_args__ = (
        CheckConstraint(
            "level IN ('junior', 'senior', 'expert')",
            name="ck_insights_seniority_snapshots_level",
        ),
        CheckConstraint(
            "previous_level IS NULL "
            "OR previous_level IN ('junior', 'senior', 'expert')",
            name="ck_insights_seniority_snapshots_previous_level",
        ),
        Index(
            "ix_insights_seniority_snapshots_user_observed",
            "user_id",
            text("observed_at DESC"),
        ),
    )
