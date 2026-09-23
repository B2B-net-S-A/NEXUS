"""Stan kontraktu i jego zamówień sprzed zakończenia współpracy (0356).

Do 09.2026 zakończenie kontraktu nadpisywało dane bez śladu: data końca linii
zamówienia, status linii i status zamówienia znikały, a sprawa offboardingu MD
snapshotuje wyłącznie pulę i stawki. „Aktywacja ponownie" wracała więc tylko
z kontraktem, a zamówienia zostawały w „Zakończonych" (zgłoszenie 23.09.2026,
kontrakt zakończony przez pomyłkę). Ten wiersz jest tym, czego brakowało, żeby
„Cofnij zakończenie" mogło przywrócić stan DOKŁADNIE sprzed zakończenia.

Jeden OTWARTY wiersz na kontrakt (częściowy UNIQUE). Kolejne wywołania w tym
samym epizodzie — dzienny cron materializujący zakończenie z przyszłą datą,
zmiana daty zakończenia — dopisują zamówienia, których jeszcze nie ma, i
aktualizują stan „po", ale nigdy nie nadpisują stanu „przed". Wskrzeszenie
kontraktu inną drogą (przedłużenie, zwykła zmiana statusu) zamyka wiersz jako
``superseded``: stan „przed" przestał opisywać to, do czego można wrócić.

Wpis zamówienia w ``orders`` (JSONB):
``{order_id, order_group_id, status_before, end_date_before,
group_status_before, status_after, end_date_after}`` — stan „po" pozwala
przy cofnięciu pominąć zamówienie, które ktoś zmienił po zakończeniu.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SNAPSHOT_STATUS_OPEN = "open"
SNAPSHOT_STATUS_REVERSED = "reversed"
SNAPSHOT_STATUS_SUPERSEDED = "superseded"
SNAPSHOT_STATUSES: tuple[str, ...] = (
    SNAPSHOT_STATUS_OPEN,
    SNAPSHOT_STATUS_REVERSED,
    SNAPSHOT_STATUS_SUPERSEDED,
)

SNAPSHOT_SOURCE_TERMINATION = "termination"
"""Stan zapisany w chwili zakończenia."""
SNAPSHOT_SOURCE_HISTORY = "history"
"""Zakończenie sprzed 0356 — stan odtworzony przy cofnięciu z historii zmian
(``order_change_events``) i zapisany dopiero jako ślad cofnięcia."""


class ContractTerminationSnapshot(Base):
    __tablename__ = "contract_termination_snapshots"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'reversed', 'superseded')",
            name="ck_contract_termination_snapshots_status",
        ),
        CheckConstraint(
            "source IN ('termination', 'history')",
            name="ck_contract_termination_snapshots_source",
        ),
        CheckConstraint(
            "status <> 'reversed' OR reversed_at IS NOT NULL",
            name="ck_contract_termination_snapshots_reversed",
        ),
        Index(
            "ux_contract_termination_snapshots_open",
            "contract_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_contract_termination_snapshots_contract", "contract_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=SNAPSHOT_STATUS_OPEN
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=SNAPSHOT_SOURCE_TERMINATION
    )
    contract_before: Mapped[dict] = mapped_column(JSONB, nullable=False)
    orders: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """Chwila cofnięcia (``reversed``) albo wskrzeszenia inną drogą (``superseded``)."""
    reversed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reversed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reversal_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    """Paragon cofnięcia: przywrócone zamówienia, pominięte z powodem,
    przeliczone wiersze importu MD. Same ID i daty — bez kwot i nazwisk."""

    def __repr__(self) -> str:
        return (
            f"<ContractTerminationSnapshot id={self.id} contract={self.contract_id} "
            f"status={self.status!r}>"
        )
