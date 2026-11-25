"""Korpus prawa asystenta prawnego: akty, wersje, jednostki redakcyjne (0784).

CHECK-i i indeksy jak w ``app/services/legal/schema.py`` (strażnik dryfu
schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
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
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services.legal import schema


class LegalAct(Base):
    """Akt z rejestru ``services/legal/acts.py`` i stan ostatniego sprawdzenia."""

    __tablename__ = "legal_acts"
    __table_args__ = (
        UniqueConstraint("key", name="uq_legal_acts_key"),
        CheckConstraint(schema.CK_ACT_SOURCE, name="ck_legal_acts_source"),
        CheckConstraint(schema.CK_ACT_STATUS, name="ck_legal_acts_fetch_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(schema.ACT_KEY_MAX), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    ident: Mapped[str] = mapped_column(String(schema.IDENT_MAX), nullable=False)
    short_name: Mapped[str] = mapped_column(
        String(schema.SHORT_NAME_MAX), nullable=False
    )
    title: Mapped[str] = mapped_column(String(schema.TITLE_MAX), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(schema.URL_MAX))
    fetch_status: Mapped[str] = mapped_column(
        String(8), nullable=False, default="pending", server_default="pending"
    )
    fetch_error: Mapped[Optional[str]] = mapped_column(String(schema.ERROR_MAX))
    checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LegalActVersion(Base):
    """Tekst jednolity albo wersja skonsolidowana z datami obowiązywania.

    Nowy wiersz z ``previous_version_id`` to zdarzenie zmiany tekstu dla
    Przepisów (część H); ``changes`` niesie listy oznaczeń dodanych, usuniętych
    i zmienionych jednostek.
    """

    __tablename__ = "legal_act_versions"
    __table_args__ = (
        UniqueConstraint(
            "act_id", "version_ident", name="uq_legal_act_versions_act_ident"
        ),
        CheckConstraint(schema.CK_VERSION_FORMAT, name="ck_legal_act_versions_format"),
        CheckConstraint(schema.CK_VERSION_DATES, name="ck_legal_act_versions_dates"),
        CheckConstraint(
            schema.CK_VERSION_CHANGES, name="ck_legal_act_versions_changes"
        ),
        Index("ix_legal_act_versions_act_valid", "act_id", "valid_from"),
        Index("ix_legal_act_versions_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    act_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("legal_acts.id", ondelete="CASCADE"), nullable=False
    )
    version_ident: Mapped[str] = mapped_column(String(schema.IDENT_MAX), nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    published_on: Mapped[Optional[date]] = mapped_column(Date)
    url: Mapped[str] = mapped_column(String(schema.URL_MAX), nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provisions_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    previous_version_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("legal_act_versions.id", ondelete="SET NULL")
    )
    changes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    #: Zmiany ogłoszone po dacie stanu prawnego tekstu jednolitego (ELI),
    #: których tekst jeszcze nie obejmuje: ``[{"id": "DU/2026/507", "date": …}]``.
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LegalProvision(Base):
    """Jednostka redakcyjna (``art. 61 § 1``) z tekstem poddrzewa."""

    __tablename__ = "legal_provisions"
    __table_args__ = (
        UniqueConstraint(
            "version_id", "ref_key", name="uq_legal_provisions_version_key"
        ),
        CheckConstraint(schema.CK_PROVISION_KIND, name="ck_legal_provisions_kind"),
        Index("ix_legal_provisions_act_key", "act_id", "ref_key"),
        Index("ix_legal_provisions_version_position", "version_id", "position"),
        Index("ix_legal_provisions_search", "search_vector", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("legal_act_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    act_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("legal_acts.id", ondelete="CASCADE"), nullable=False
    )
    ref: Mapped[str] = mapped_column(String(schema.REF_MAX), nullable=False)
    ref_key: Mapped[str] = mapped_column(String(schema.REF_MAX), nullable=False)
    article: Mapped[str] = mapped_column(String(24), nullable=False)
    kind: Mapped[str] = mapped_column(String(4), nullable=False)
    depth: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    parent_key: Mapped[Optional[str]] = mapped_column(String(schema.REF_MAX))
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[Optional[str]] = mapped_column(String(schema.HEADING_MAX))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    repealed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    search_vector: Mapped[Optional[str]] = mapped_column(
        TSVECTOR, Computed(schema.SEARCH_VECTOR_EXPR, persisted=True)
    )
