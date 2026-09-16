"""Runy integracji zewnętrznych (scrapery pracuj.pl / JJIT) i ich zdarzenia.

Scrapery chodzą poza NEXUS-em. Do tej pory jedynym śladem ich pracy były
wiadomości na Slacku — brak runu wyglądał tak samo jak brak kandydatów.
Ten model daje trzy odpowiedzi, które operator musi umieć dostać bez logów
z cudzego laptopa:

- **kiedy ostatnio poszło i z jakim wynikiem** (``IntegrationRun``),
- **co dokładnie zrobiono z każdą aplikacją** — kandydat w NEXUS/Traffit,
  dopasowane rekrutacje, błąd (``IntegrationRunEvent``),
- **czy alert o zastoju już poszedł** (``IntegrationAlertState``), żeby pętla
  sprawdzająca co 30 min nie zamieniła Slacka w spam.

Wzorowane na ``traffit_sync_state`` (ta sama semantyka ``last_status``:
ok / errors / failed), ale per run, nie per faza — scraper może chodzić kilka
razy dziennie (import, replay, test) i każdy przebieg ma własną historię.
Migracja 0314.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base
from app.models.base import TimestampMixin

# Znane źródła — słownik zamknięty świadomie: detektor zastoju alarmuje o
# KAŻDYM źródle z tej listy, także takim, które nigdy nie zaraportowało.
INTEGRATION_SOURCES: tuple[str, ...] = ("pracuj", "jjit")
INTEGRATION_SOURCE_LABELS: dict[str, str] = {
    "pracuj": "Pracuj.pl",
    "jjit": "JustJoinIT / RocketJobs",
}

RUN_STATUSES: tuple[str, ...] = ("running", "ok", "errors", "failed")
RUN_MODES: tuple[str, ...] = ("import", "replay", "test", "dry_run")
EVENT_ACTIONS: tuple[str, ...] = (
    "created",
    "duplicate",
    "cv_refreshed",
    "error",
    "skipped",
)


class IntegrationRun(Base, TimestampMixin):
    __tablename__ = "integration_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="import")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    host: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Liczniki z podsumowania scrapera: created, duplicates, cv_refreshed,
    # errors, skipped, nexus_pushed, nexus_created, nexus_existing, nexus_jobs…
    # JSONB, bo każde źródło ma trochę inny zestaw, a raport i tak agreguje
    # tylko wspólne klucze.
    stats: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oauth_client_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    events: Mapped[list["IntegrationRunEvent"]] = relationship(
        "IntegrationRunEvent",
        back_populates="run",
        cascade="all, delete-orphan",
        lazy="noload",
    )

    def __repr__(self) -> str:  # pragma: no cover - diagnostyka
        return (
            f"<IntegrationRun id={self.id} source={self.source} status={self.status}>"
        )


class IntegrationRunEvent(Base):
    __tablename__ = "integration_run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("integration_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    # ID aplikacji w portalu (JJIT uuid / pracuj candidateId) — klucz do
    # „czy tę aplikację już widzieliśmy" po stronie NEXUS-a.
    external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    traffit_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    offer_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # [{"job_id": 123, "title": "...", "score": 71.2}, ...]
    matched_jobs: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped["IntegrationRun"] = relationship(
        "IntegrationRun", back_populates="events"
    )


class IntegrationAlertState(Base):
    __tablename__ = "integration_alert_state"

    source: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_alert_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_alert_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


__all__ = [
    "EVENT_ACTIONS",
    "INTEGRATION_SOURCES",
    "INTEGRATION_SOURCE_LABELS",
    "IntegrationAlertState",
    "IntegrationRun",
    "IntegrationRunEvent",
    "RUN_MODES",
    "RUN_STATUSES",
]
