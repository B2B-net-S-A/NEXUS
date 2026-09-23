"""Przebiegi importu rejestru umów z Excela działu (0358).

Wzór: ``ClientImportRun``/``ClientImportRow`` (``models/client_directory.py``).
Przebieg ``dry_run`` zapisuje wyłącznie liczniki (ta sama ścieżka co zapis,
zakończona rollbackiem) — on odblokowuje „Zastosuj” dla tego samego pliku.
Przebieg ``applied`` trzyma każdy wiersz pliku ze stanem sprzed zmiany
(``snapshot_before``), dzięki czemu „Cofnij” przywraca poprzedni stan
zaktualizowanych wierszy i usuwa utworzone.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin

_JSON = JSON().with_variant(JSONB(), "postgresql")


class B2BRegisterImportRun(Base, TimestampMixin):
    __tablename__ = "b2b_register_import_runs"
    __table_args__ = (
        CheckConstraint(
            "mode IN ('dry_run', 'applied', 'rolled_back')",
            name="ck_b2b_register_import_runs_mode",
        ),
        CheckConstraint(
            "char_length(source_sha256) = 64",
            name="ck_b2b_register_import_runs_sha256",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    # Same liczby — bez nazwisk (lista przebiegów widzi je w UI admina).
    counters: Mapped[dict[str, Any]] = mapped_column(
        _JSON, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    # Id wierszy, którym ten przebieg ustawił `excel_missing_since` —
    # cofnięcie zdejmuje flagę wyłącznie z nich.
    missing_marked_ids: Mapped[list[int]] = mapped_column(
        _JSON, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    rolled_back_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rolled_back_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class B2BRegisterImportRow(Base, TimestampMixin):
    __tablename__ = "b2b_register_import_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("b2b_register_import_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sheet: Mapped[str] = mapped_column(String(64), nullable=False)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(
        _JSON, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    parsed: Mapped[Optional[dict[str, Any]]] = mapped_column(_JSON, nullable=True)
    matches: Mapped[Optional[dict[str, Any]]] = mapped_column(_JSON, nullable=True)
    # created | updated | unchanged | skipped | generator_conflict |
    # annex_flag | annex_unmatched
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    generated_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("b2b_generated_contracts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Stan kolumn wiersza rejestru sprzed tego przebiegu (tylko `updated`).
    snapshot_before: Mapped[Optional[dict[str, Any]]] = mapped_column(
        _JSON, nullable=True
    )
