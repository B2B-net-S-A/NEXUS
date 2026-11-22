"""Masowa wysyłka nowej umowy B2B do aktywnych kontraktorów (E5b, 0756).

Paczka (``B2BMassSendBatch``) to jedna wysyłka z rejestru Generatora: kto ją
zaczął (z jego skrzynki M365 idą maile), kto podpisuje za B2Bnetwork i ile dni
ma link. Pozycja (``B2BMassSendItem``) to jedna osoba: kontrakt, z którego
wzięto osobę, wiersz Generatora z danymi umowy, nowy wiersz Generatora
i wniosek o podpis. DDL: ``services/b2b_mass_send/schema_sql.py``.

Stany pozycji: ``pending`` (czeka na wiersz Generatora) → ``created`` (wiersz
jest, czeka na wysyłkę) → ``sent``; poza tym ``failed`` (z błędem),
``needs_review`` (brakuje danych do umowy — pola w ``missing``) i ``skipped``
(powód w ``reason``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services.b2b_mass_send.schema_sql import (
    BATCH_STATUSES,
    ITEM_STATUSES,
    LIVE_ITEM_STATUSES,
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class B2BMassSendBatch(Base, TimestampMixin):
    __tablename__ = "b2b_mass_send_batches"
    __table_args__ = (
        CheckConstraint(
            _in("status", BATCH_STATUSES), name="ck_b2b_mass_send_batches_status"
        ),
        CheckConstraint(
            "link_days BETWEEN 1 AND 30", name="ck_b2b_mass_send_batches_days"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="running", server_default="running"
    )
    started_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    company_signer_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    link_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    skip_ending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    # Wzór, na którym powstają umowy („obecny wzór Generatora” do czasu, gdy
    # admin podepnie nowy).
    template_label: Mapped[str] = mapped_column(String(160), nullable=False)
    # Liczby z chwili planu (stan → liczba), żeby postęp miał punkt odniesienia.
    planned: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class B2BMassSendItem(Base, TimestampMixin):
    __tablename__ = "b2b_mass_send_items"
    __table_args__ = (
        CheckConstraint(
            _in("status", ITEM_STATUSES), name="ck_b2b_mass_send_items_status"
        ),
        CheckConstraint(
            "jsonb_typeof(missing) = 'array'", name="ck_b2b_mass_send_items_missing"
        ),
        Index("ix_b2b_mass_send_items_batch_status", "batch_id", "status"),
        Index(
            "ix_b2b_mass_send_items_generated",
            "generated_contract_id",
            postgresql_where=text("generated_contract_id IS NOT NULL"),
        ),
        Index(
            "uq_b2b_mass_send_items_live_person",
            "candidate_id",
            unique=True,
            postgresql_where=text(_in("status", LIVE_ITEM_STATUSES)),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("b2b_mass_send_batches.id", ondelete="CASCADE"), nullable=False
    )
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    source_generated_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("b2b_generated_contracts.id", ondelete="SET NULL"), nullable=True
    )
    generated_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("b2b_generated_contracts.id", ondelete="SET NULL"), nullable=True
    )
    signing_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("b2b_signing_requests.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    missing: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
