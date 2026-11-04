"""Dokumenty kontraktów z folderu „Umowy pracowników” na SharePoincie (0402).

* ``ContractDocSpRun`` — przebieg pierwszego pobrania: spis folderu i podgląd
  (``listing`` → ``preview``), zapis (``applying`` → ``applied``), cofnięcie.
* ``ContractDocSpRunItem`` — wiersze raportu przebiegu: przypisania plików do
  kontraktów, kontrakty bez folderu, foldery bez kontraktu, pominięte pliki.
* ``ContractDocSpItem`` — stan każdego pliku z SharePointa dla synchronizacji
  (co już weszło, co czeka na kontrakt albo na decyzję człowieka).
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")

RUN_MODES = ("listing", "preview", "applying", "applied", "rolled_back", "failed")
ITEM_STATUSES = (
    "imported",
    "skipped",
    "waiting_contract",
    "review",
    "dismissed",
    "pushed",
)


class ContractDocSpRun(Base, TimestampMixin):
    __tablename__ = "contract_doc_sp_runs"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('listing', 'preview', 'applying', 'applied', "
            "'rolled_back', 'failed')",
            name="ck_contract_doc_sp_runs_mode",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    drive_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    folder_item_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Same liczby — bez nazwisk (paragon w app_settings je kopiuje).
    counters: Mapped[dict[str, Any]] = mapped_column(
        _JSON, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Dzierżawa pracy w tle — przebieg przerwany deployem podejmuje pętla.
    lease_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    applied_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rolled_back_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rolled_back_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ContractDocSpRunItem(Base, TimestampMixin):
    __tablename__ = "contract_doc_sp_run_items"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('assignment', 'contract', 'folder', 'file')",
            name="ck_contract_doc_sp_run_items_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("contract_doc_sp_runs.id", ondelete="CASCADE"), nullable=False
    )
    # assignment = plik → kontrakt; contract = kontrakt bez folderu/dokumentów
    # albo pominięty; folder = folder bez kontraktu; file = plik pominięty.
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    folder_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    item_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    doc_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    person_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    match_kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    reasons: Mapped[list[str]] = mapped_column(
        _JSON, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    note: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    selected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # info | pending | done | skipped_existing | not_selected | failed
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="info", server_default="info"
    )
    contract_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contract_documents.id", ondelete="SET NULL"), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class ContractDocSpItem(Base):
    __tablename__ = "contract_doc_sp_items"
    __table_args__ = (
        CheckConstraint(
            "status IN ('imported', 'skipped', 'waiting_contract', 'review', "
            "'dismissed', 'pushed')",
            name="ck_contract_doc_sp_items_status",
        ),
    )

    item_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    drive_id: Mapped[str] = mapped_column(String(255), nullable=False)
    folder_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    c_tag: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    reasons: Mapped[list[str]] = mapped_column(
        _JSON, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    proposed_contract_ids: Mapped[list[int]] = mapped_column(
        _JSON, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
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
