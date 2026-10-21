"""Prepy w Teams: spotkanie, transkrypt i ocena (migracja 0370, 23.09.2026).

Przed każdą rozmową u klienta są DWA prepy z kandydatem (Prep 1 prowadzi
Delivery Lead, Prep 2 — rekruter). NEXUS zakłada spotkanie w kalendarzu
organizatora przez aplikację (app-only), po spotkaniu pobiera transkrypt
z Teams, zapisuje podsumowanie jako notatkę i ocenia prep.

Każda tabela ma własne ``candidate_id … ON DELETE CASCADE``:
``calendar_events.candidate_id`` jest ``SET NULL``, więc wydarzenie przeżywa
usunięcie kandydata — transkrypt i ocena (dane osobowe) nie mogą.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Stan włączenia automatycznej transkrypcji po utworzeniu spotkania.
TRANSCRIPTION_SETUP_STATES = ("pending", "enabled", "failed", "disabled")
# Stan pobrania transkryptu. `missing` = spotkanie się odbyło (albo minęła jego
# godzina), a transkryptu nie było — prep „bez nagrania”.
TRANSCRIPT_STATES = ("waiting", "fetched", "missing", "cancelled", "forbidden", "error")
REVIEW_STATUSES = ("ok", "unavailable")
REVIEW_LEVELS = ("weak", "ok", "good")
CANDIDATE_RESPONSES = ("none", "accepted", "tentative", "declined")


class PrepMeeting(Base):
    __tablename__ = "prep_meetings"
    __table_args__ = (
        CheckConstraint("prep_no IN (1, 2)", name="ck_prep_meetings_prep_no"),
        CheckConstraint(
            "transcription_setup IN ('pending','enabled','failed','disabled')",
            name="ck_prep_meetings_transcription_setup",
        ),
        CheckConstraint(
            "transcript_status IN "
            "('waiting','fetched','missing','cancelled','forbidden','error')",
            name="ck_prep_meetings_transcript_status",
        ),
        CheckConstraint(
            "candidate_response IS NULL OR candidate_response IN "
            "('none','accepted','tentative','declined')",
            name="ck_prep_meetings_candidate_response",
        ),
        Index("ix_prep_meetings_fetch_queue", "transcript_status", "next_fetch_at"),
        Index("ix_prep_meetings_pair", "candidate_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    calendar_event_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("calendar_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    prep_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    organizer_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    organizer_upn: Mapped[str] = mapped_column(String(320), nullable=False)
    # Identyfikator obiektu w Entra — ścieżki `onlineMeetings` go wymagają.
    organizer_aad_id: Mapped[Optional[str]] = mapped_column(String(64))
    scheduled_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    online_meeting_id: Mapped[Optional[str]] = mapped_column(String(512))
    transcription_setup: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    transcript_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="waiting"
    )
    fetch_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    next_fetch_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Klasa błędu albo kod HTTP — nigdy treść odpowiedzi ani transkryptu.
    last_error: Mapped[Optional[str]] = mapped_column(String(120))
    # Odpowiedź kandydata z Outlooka prowadzącego (0453, 17.10.2026, D5).
    # NULL = jeszcze nie sprawdzano (prep sprzed 0453); 'none' = bez odpowiedzi.
    candidate_response: Mapped[Optional[str]] = mapped_column(String(20))
    candidate_response_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    # Inny termin zaproponowany przez kandydata („Zaproponuj nowy termin”).
    proposed_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    proposed_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    outlook_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PrepTranscript(Base):
    """Pełny transkrypt prepu — bez limitu czasu (decyzja 23.09.2026)."""

    __tablename__ = "prep_transcripts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    prep_meeting_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("prep_meetings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    graph_transcript_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    vtt: Mapped[str] = mapped_column(Text, nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False)
    # [{name, role: candidate|staff|unknown, user_id, seconds}]
    speakers: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    candidate_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    staff_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    unknown_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    talk_share: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 3))
    duration_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    summary_note_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PrepReview(Base):
    """Ocena prepu. ``level`` liczy KOD z punktów i udziału kandydata;
    awaria modelu = ``status='unavailable'`` i ``level=NULL`` — nigdy „słaby”."""

    __tablename__ = "prep_reviews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ok','unavailable')", name="ck_prep_reviews_status"
        ),
        CheckConstraint(
            "level IS NULL OR level IN ('weak','ok','good')",
            name="ck_prep_reviews_level",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    prep_meeting_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("prep_meetings.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    level: Mapped[Optional[str]] = mapped_column(String(10))
    coverage: Mapped[Optional[Decimal]] = mapped_column(Numeric(4, 3))
    # {must_haves: [...], client_questions: [...], own_projects: {...}}
    criteria: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    summary: Mapped[Optional[str]] = mapped_column(Text)
    remaining: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
    model: Mapped[Optional[str]] = mapped_column(String(80))
    prompt_version: Mapped[Optional[str]] = mapped_column(String(40))
    input_hash: Mapped[Optional[str]] = mapped_column(String(64))
    # 0505: wersja ustawień oceny (``prep_review_configs.id``); NULL = startowe.
    config_version: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PrepReviewConfigVersion(Base):
    """Opublikowana wersja ustawień oceny prepów (0505, 22.10.2026).

    Obowiązuje wiersz o najwyższym ``id``; treść waliduje
    ``services/prep_review_config.PrepReviewConfig``.
    """

    __tablename__ = "prep_review_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text)


# Dlaczego rozmowa u klienta odbywa się bez Prepu 2 (0482, 20.10.2026).
PREP2_SKIP_REASONS = ("no_slot", "short_notice", "prep1_covered", "other")


class Prep2Skip(Base):
    """Rozmowa u klienta bez Prepu 2 — wyjątek z powodem (0482, 20.10.2026).

    Decyzja Artura: Prep 2 da się pominąć tylko tuż przed rozmową, po
    odbytym Prepie 1, z powodem i z krótkim telefonem do kandydata przed
    rozmową (``call_at``). Jeden wpis na rozmowę; wpis bez telefonu
    (``call_done_at``) zostaje zadaniem „Telefon przed rozmową”.
    """

    __tablename__ = "prep2_skips"
    __table_args__ = (
        CheckConstraint(
            "reason IN ('no_slot','short_notice','prep1_covered','other')",
            name="ck_prep2_skips_reason",
        ),
        CheckConstraint(
            "reason <> 'other' OR reason_note IS NOT NULL",
            name="ck_prep2_skips_other_note",
        ),
        Index("ix_prep2_skips_pair", "candidate_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    interview_event_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("calendar_events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_note: Mapped[Optional[str]] = mapped_column(Text)
    call_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    call_done_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    call_done_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    call_note: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
