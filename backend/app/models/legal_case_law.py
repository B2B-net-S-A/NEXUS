"""Orzecznictwo dla asystenta prawnego (0781).

CHECK-i i indeksy jak w ``app/services/legal_case_law/schema.py`` (strażnik
dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services.legal_case_law import schema


class LegalCase(Base):
    """Orzeczenie (albo interpretacja) pobrane ze źródła z API."""

    __tablename__ = "legal_cases"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_legal_cases_source_id"),
        CheckConstraint(schema.CK_SOURCE, name="ck_legal_cases_source"),
        CheckConstraint(schema.CK_COURT_TYPE, name="ck_legal_cases_court_type"),
        CheckConstraint(schema.CK_KIND, name="ck_legal_cases_kind"),
        CheckConstraint(schema.CK_TOPICS, name="ck_legal_cases_topics"),
        Index("ix_legal_cases_court_date", "court_type", "judgment_date"),
        Index("ix_legal_cases_search", "search_tsv", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    source_id: Mapped[str] = mapped_column(String(schema.SOURCE_ID_MAX), nullable=False)
    signature: Mapped[str] = mapped_column(String(schema.SIGNATURE_MAX), nullable=False)
    court: Mapped[str] = mapped_column(String(schema.COURT_MAX), nullable=False)
    court_type: Mapped[str] = mapped_column(String(16), nullable=False)
    judgment_date: Mapped[Optional[date]] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    url: Mapped[str] = mapped_column(String(schema.URL_MAX), nullable=False)
    #: Teza albo sentencja ze źródła; SAOS ma ją rzadko.
    summary: Mapped[Optional[str]] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Klucze tematów wstępnego zasilenia (``topics.TOPICS``).
    topics: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb")
    )
    search_tsv: Mapped[Optional[Any]] = mapped_column(TSVECTOR)
    #: Skrót treści, z której powstał wektor; inny niż ``content_sha256`` = do przeliczenia.
    embedded_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
