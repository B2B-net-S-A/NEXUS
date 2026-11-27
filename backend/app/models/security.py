"""Ekran Ustawienia → Bezpieczeństwo (0799) — DDL w ``services/security_schema.py``."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SecurityFinding(Base):
    __tablename__ = "security_findings"
    __table_args__ = (
        Index("uq_security_findings_fingerprint", "source", "fingerprint", unique=True),
        Index("ix_security_findings_status", "status", "severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    # Narzędzie w źródle (zizmor, trivy-image) — „pełny skan” zamyka tylko jego znaleziska.
    scanner: Mapped[Optional[str]] = mapped_column(String(40))
    fingerprint: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(300))
    evidence: Mapped[Optional[str]] = mapped_column(Text)
    impact: Mapped[Optional[str]] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # open / excepted / fixed (CHECK w DDL). Wyjątek po terminie liczy się jak open.
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="open", server_default="open"
    )
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    exception_reason: Mapped[Optional[str]] = mapped_column(Text)
    exception_until: Mapped[Optional[date]] = mapped_column(Date)
    exception_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    closed_note: Mapped[Optional[str]] = mapped_column(Text)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (
        Index(
            "uq_security_events_ref",
            "source",
            "ref",
            unique=True,
            postgresql_where=text("ref IS NOT NULL"),
        ),
        Index("ix_security_events_occurred", text("occurred_at DESC")),
        Index(
            "ix_security_events_source_kind", "source", "kind", text("occurred_at DESC")
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(10), nullable=False, default="info", server_default="info"
    )
    # Bez danych osobowych: `security_ingest.scrub` zamienia IP i e-maile.
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    ref: Mapped[Optional[str]] = mapped_column(String(120))
    link: Mapped[Optional[str]] = mapped_column(String(500))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Konto serwisowe, które przysłało zdarzenie (bez FK: konto można usunąć).
    service_account_id: Mapped[Optional[int]] = mapped_column(Integer)


class SecurityRoutine(Base):
    __tablename__ = "security_routines"
    __table_args__ = (Index("uq_security_routines_key", "key", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # week / month / quarter (CHECK w DDL).
    cadence: Mapped[str] = mapped_column(String(10), nullable=False)
    owner_label: Mapped[str] = mapped_column(String(80), nullable=False)
    # Rutyna odhaczana sama przez synchronizację źródła (np. `ci`).
    auto_source: Mapped[Optional[str]] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_done_on: Mapped[Optional[date]] = mapped_column(Date)
    next_due_on: Mapped[date] = mapped_column(Date, nullable=False)
    last_note: Mapped[Optional[str]] = mapped_column(Text)
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SecuritySourceState(Base):
    __tablename__ = "security_source_states"

    source: Mapped[str] = mapped_column(String(20), primary_key=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_ok_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(String(300))
    detail: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
