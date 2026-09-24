"""Praktykant — program wdrożenia i codzienna lista telefonów (0371).

Decyzje Artura 24.09.2026: nowa osoba przez pierwsze 40 dni roboczych dzwoni
wyłącznie do kandydatów z listy układanej co noc (popyt × luki w danych ×
telefon nikomu nie szkodzi) i zapisuje fakty, bez których rekruter dzwoni
na próżno. Dzień jest zaliczony, gdy każda pozycja listy ma wynik.

Pozycja listy jest jednocześnie dziennikiem telefonu: po niej generator
rozpoznaje „dzwoniono w ostatnich 60 dniach”, „niezainteresowany” (nigdy
więcej od praktykantów) i „zły numer” (dopóki telefon się nie zmieni).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

TRAINEE_PROGRAM_STATUSES = ("active", "completed", "ended")
TRAINEE_PROGRAM_DECISIONS = ("promoted", "extended", "ended")
TRAINEE_OUTCOMES = ("call", "noanswer", "later", "wrong", "declined")
TRAINEE_QUALITY_VERDICTS = ("ok", "issue")


def _values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class TraineeProgram(Base):
    __tablename__ = "trainee_programs"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_values(TRAINEE_PROGRAM_STATUSES)})",
            name="ck_trainee_programs_status",
        ),
        CheckConstraint(
            f"decision IS NULL OR decision IN ({_values(TRAINEE_PROGRAM_DECISIONS)})",
            name="ck_trainee_programs_decision",
        ),
        CheckConstraint(
            "workdays BETWEEN 1 AND 250 AND extended_days BETWEEN 0 AND 250 "
            "AND daily_list_size BETWEEN 1 AND 300",
            name="ck_trainee_programs_numbers",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    workdays: Mapped[int] = mapped_column(
        Integer, nullable=False, default=40, server_default="40"
    )
    extended_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    daily_list_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=70, server_default="70"
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="active", server_default="active"
    )
    decision_notified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    @property
    def total_workdays(self) -> int:
        return int(self.workdays or 0) + int(self.extended_days or 0)


class TraineeCallList(Base):
    __tablename__ = "trainee_call_lists"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "list_date", name="uq_trainee_call_lists_user_date"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    list_date: Mapped[date] = mapped_column(Date, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )


class TraineeCallItem(Base):
    __tablename__ = "trainee_call_items"
    __table_args__ = (
        UniqueConstraint(
            "list_id", "candidate_id", name="uq_trainee_call_items_list_candidate"
        ),
        CheckConstraint(
            f"outcome IS NULL OR outcome IN ({_values(TRAINEE_OUTCOMES)})",
            name="ck_trainee_call_items_outcome",
        ),
        CheckConstraint(
            "(outcome IS NULL) = (closed_at IS NULL)",
            name="ck_trainee_call_items_closed",
        ),
        CheckConstraint(
            "(outcome = 'later') = (later_date IS NOT NULL)",
            name="ck_trainee_call_items_later",
        ),
        CheckConstraint(
            f"quality_verdict IS NULL OR quality_verdict IN "
            f"({_values(TRAINEE_QUALITY_VERDICTS)})",
            name="ck_trainee_call_items_quality",
        ),
        Index("ix_trainee_call_items_candidate_date", "candidate_id", "list_date"),
        Index("ix_trainee_call_items_user_date", "user_id", "list_date"),
        Index(
            "ix_trainee_call_items_later",
            "user_id",
            "later_date",
            postgresql_where=text("outcome = 'later'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    list_id: Mapped[int] = mapped_column(
        ForeignKey("trainee_call_lists.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    list_date: Mapped[date] = mapped_column(Date, nullable=False)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    reasons: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retry_after: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    outcome: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    later_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    phone_snapshot: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    call_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("calls.id", ondelete="SET NULL"), nullable=True
    )
    note_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    quality_verdict: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    quality_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    quality_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    quality_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
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
