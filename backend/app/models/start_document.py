"""Dokumenty do startu: lista klienta i stan dokumentów pary (0649).

``ClientStartDocument`` to pozycja listy klienta, ``PlacementStartDocument``
to stan tej pozycji dla pary (kandydat, rekrutacja). Brak wiersza pary znaczy
„brakuje”, dlatego nie ma hooków na etapach: pary w zakresie liczy się przy
odczycie (``services/start_documents.py``). Reguły:
``docs/claude/kontrakty/dokumenty-do-startu.md``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class ClientStartDocument(Base, TimestampMixin):
    __tablename__ = "client_start_documents"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('file', 'pesel', 'agreement')",
            name="ck_client_start_documents_kind",
        ),
        CheckConstraint("btrim(name) <> ''", name="ck_client_start_documents_name"),
        CheckConstraint(
            "offset_days BETWEEN -30 AND 30", name="ck_client_start_documents_offset"
        ),
        Index(
            "ix_client_start_documents_client",
            "client_id",
            postgresql_where=text("archived_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="file", server_default="file"
    )
    required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    #: Dni robocze względem startu kontraktu (ujemne = przed startem).
    offset_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=-2, server_default="-2"
    )
    link_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    #: Wzór DOCX z tabelą danych osoby: NEXUS wstawia dane z umowy (NDA Nordei).
    fill_from_agreement: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    template_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    template_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    template_content_type: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True
    )
    #: Usunięta pozycja zostaje: pary mogą mieć już przy niej plik.
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PlacementStartDocument(Base, TimestampMixin):
    __tablename__ = "placement_start_documents"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "candidate_id",
            "job_id",
            name="uq_placement_start_documents_pair",
        ),
        CheckConstraint(
            "status IN ('delivered', 'returned', 'not_applicable')",
            name="ck_placement_start_documents_status",
        ),
        Index("ix_placement_start_documents_pair", "candidate_id", "job_id"),
        Index("ix_placement_start_documents_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("client_start_documents.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    #: Zwykłe pole (decyzja Artura 05.11.2026). Nie idzie do logów ani historii,
    #: a sanitize stagingu je czyści. Odczyt tylko przez trasę z bramką DL-a.
    pesel: Mapped[Optional[str]] = mapped_column(String(11), nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    checked_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    #: Powód zwrotu albo „Nie dotyczy”.
    reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    reason_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
