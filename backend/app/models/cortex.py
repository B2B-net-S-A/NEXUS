"""Cortex — skill-fact store (warstwa „central intelligence").

Fundament modułu Cortex (docs/cortex/00-discovery.md): fakty kompetencyjne
z metryką pochodzenia i świeżości, zamiast martwego ``candidates.skills``
(0,3% wypełnień na prod 2026-07). Każdy fakt niesie:

- skąd wiemy (``source``: traffit / cv_llm / screening),
- kiedy fakt był prawdziwy (``observed_at`` — data sygnału, NIE ekstrakcji;
  dla Traffita NULL, bo źródło nie daje daty),
- jak bardzo ufamy (``confidence``) i na jakiej podstawie (``evidence`` —
  surowy token z Traffita albo cytat z CV).

UNIQUE(candidate_id, skill_id, source) → upsert per źródło: re-run backfillu
jest idempotentnym odświeżeniem, a źródła koegzystują jako osobne wiersze
(precedencja odczytu: screening > cv_llm > traffit).

``cortex_unmatched_terms`` domyka pętlę kuracji taksonomii: tokeny, których
nie rozwiązał ALIAS_MAP, lądują tu z licznikiem wystąpień — admin rozszerza
słownik ``skills``/``skill_aliases`` (seed migracją) i ponawia backfill.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CortexSkillFact(Base):
    __tablename__ = "cortex_skill_facts"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "skill_id",
            "source",
            name="uq_cortex_fact_cand_skill_source",
        ),
        Index("ix_cortex_facts_skill_source", "skill_id", "source"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Zawsze skill kanoniczny z taksonomii — fakty nie przechowują surowych nazw.
    skill_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("skills.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # traffit | cv_llm | screening (screening zarezerwowane na później).
    source: Mapped[str] = mapped_column(String(20), nullable=False)

    # junior|mid|senior — NULL gdy źródło nie daje sygnału (Traffit nigdy nie daje).
    level: Mapped[Optional[str]] = mapped_column(String(20))
    years: Mapped[Optional[int]] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.8, server_default="0.8"
    )
    # Audyt: surowy token (traffit) lub krótki cytat z CV (cv_llm, ≤300 znaków).
    evidence: Mapped[Optional[str]] = mapped_column(Text)

    # Kiedy fakt był prawdziwy (np. koniec ostatniej roli używającej skilla).
    # NULL = nie wiemy — uczciwie zasila kubełek „unknown" w widoku świeżości.
    observed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    skill = relationship("Skill")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CortexSkillFact candidate={self.candidate_id} "
            f"skill={self.skill_id} source={self.source}>"
        )


class CortexUnmatchedTerm(Base):
    __tablename__ = "cortex_unmatched_terms"
    __table_args__ = (UniqueConstraint("term", name="uq_cortex_unmatched_term"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Zawsze lowercase/trim — normalizacja robi to przed zapisem.
    term: Mapped[str] = mapped_column(Text, nullable=False)
    occurrences: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # new → (kurator rozszerza taksonomię) → mapped, albo ignored.
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="new", server_default="new"
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<CortexUnmatchedTerm term={self.term!r} n={self.occurrences}>"
