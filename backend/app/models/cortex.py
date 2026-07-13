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
    CheckConstraint,
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
from sqlalchemy.dialects.postgresql import JSONB
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
        # Integralność wartości na poziomie DB (nie tylko clamp_* w aplikacji).
        CheckConstraint(
            "source IN ('traffit', 'cv_llm', 'screening')",
            name="ck_cortex_fact_source",
        ),
        CheckConstraint(
            "level IS NULL OR level IN ('junior', 'mid', 'senior')",
            name="ck_cortex_fact_level",
        ),
        CheckConstraint(
            "years IS NULL OR (years >= 0 AND years <= 40)",
            name="ck_cortex_fact_years",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_cortex_fact_confidence",
        ),
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

    # Provenance — pozwala odtworzyć/wycofać wynik konkretnego runu.
    # ``run_id`` to miękka referencja do ``cortex_extraction_runs.id`` (bez FK,
    # żeby prune runów nie kaskadował na miliony faktów).
    extractor_version: Mapped[Optional[str]] = mapped_column(String(40))
    run_id: Mapped[Optional[int]] = mapped_column(BigInteger)
    # sha256 surowego źródła (traffit_technologie) — fingerprint pod skip-unchanged.
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    # Namiar na rekord źródłowy (np. traffit candidate id) — zarezerwowane.
    source_ref: Mapped[Optional[str]] = mapped_column(String(120))

    skill = relationship("Skill")

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CortexSkillFact candidate={self.candidate_id} "
            f"skill={self.skill_id} source={self.source}>"
        )


class CortexUnmatchedTerm(Base):
    """Kolejka kuracji słownika — tokeny spoza taksonomii, po jednym wierszu na term.

    ``occurrences`` = liczba UNIKALNYCH kandydatów z tym terminem (nie liczba
    uruchomień backfillu). Utrzymywane idempotentnie: licznik rośnie tylko przy
    pierwszej obserwacji danego ``(term, candidate, source)`` (patrz
    ``cortex_unmatched_observations`` + ``fact_store.record_unmatched``), więc
    rerun na niezmienionych danych NIE zawyża licznika.
    """

    __tablename__ = "cortex_unmatched_terms"
    __table_args__ = (
        UniqueConstraint("term", name="uq_cortex_unmatched_term"),
        CheckConstraint(
            "status IN ('new', 'mapped', 'ignored')",
            name="ck_cortex_unmatched_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Zawsze lowercase/trim — normalizacja robi to przed zapisem.
    term: Mapped[str] = mapped_column(Text, nullable=False)
    occurrences: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # new → (kurator rozszerza taksonomię) → mapped, albo ignored.
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="new", server_default="new"
    )
    # Audyt decyzji kuracji (kto zmapował/zignorował i kiedy) — migracja 0161.
    curated_by: Mapped[Optional[str]] = mapped_column(String(120))
    curated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<CortexUnmatchedTerm term={self.term!r} n={self.occurrences}>"


class CortexUnmatchedObservation(Base):
    """Relacja term ↔ kandydat ↔ źródło — czyni licznik unmatched idempotentnym.

    UNIQUE(term, candidate_id, source): powtórna obserwacja tego samego terminu
    u tego samego kandydata jest no-op (odświeża tylko ``last_seen_at``), więc
    ``cortex_unmatched_terms.occurrences`` liczy unikalnych kandydatów, a nie
    liczbę przebiegów backfillu.
    """

    __tablename__ = "cortex_unmatched_observations"
    __table_args__ = (
        UniqueConstraint(
            "term", "candidate_id", "source", name="uq_cortex_unmatched_obs"
        ),
        Index("ix_cortex_unmatched_obs_term", "term"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    term: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="traffit"
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CortexUnmatchedObservation term={self.term!r} "
            f"candidate={self.candidate_id}>"
        )


class CortexExtractionRun(Base):
    """Trwały ślad przebiegu ekstrakcji Cortexa (zastępuje in-memory ``_TRAFFIT_JOB``).

    Restart-safe status + single-flight (advisory lock w API) + orphan reaper.
    Wzorzec z ``traffit_sync_state`` — patrz [[api/cortex.py]].
    """

    __tablename__ = "cortex_extraction_runs"
    __table_args__ = (
        Index("ix_cortex_runs_status_started", "status", "started_at"),
        Index("ix_cortex_runs_started", "started_at"),
        CheckConstraint(
            "run_type IN ('manual', 'daily', 'full')",
            name="ck_cortex_run_type",
        ),
        CheckConstraint(
            "status IN ('running', 'ok', 'errors', 'failed')",
            name="ck_cortex_run_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_type: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="traffit"
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="running"
    )
    triggered_by: Mapped[Optional[str]] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cursor_candidate_id: Mapped[Optional[int]] = mapped_column(Integer)
    stats: Mapped[Optional[dict]] = mapped_column(JSONB)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CortexExtractionRun id={self.id} type={self.run_type} "
            f"status={self.status}>"
        )
