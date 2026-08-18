"""Powiadomienia Delivery Leada — z logiem obsłużenia i czasem reakcji.

**Dlaczego osobna tabela, a nie ``notifications``.** Tamta zna wyłącznie
``is_read``: nie wie, KTO i KIEDY sprawę załatwił, więc nie da się z niej
policzyć czasu reakcji ani zbudować raportu, którego żąda ticket. Ma też
unikalny indeks dobowy ``ix_notif_dedup_daily``, który jest tam poprawny, ale
tutaj tłumiłby powtórki, oraz fail-closed filtr widoczności
(``api/notifications.py``), przez który rola Finanse nie zobaczyłaby tych
wpisów niezależnie od nadanych uprawnień.

**Powtórka co 7 dni jest NOWYM WIERSZEM, nie aktualizacją.** Ticket wymaga, by
każde ponowienie było widoczne osobno w historii i w eksporcie — inaczej
raport pokazywałby jeden alert zamiast sześciu tygodni ignorowania sprawy.
Dlatego numer tygodnia wchodzi w skład ``dedupe_key``: bez tego atomowy claim
``ON CONFLICT DO NOTHING`` zdusiłby każde ponowienie i alert pojawiłby się
dokładnie raz w życiu.

Wiersze NIE są kasowane — ani przy obsłużeniu, ani gdy przyczyna ustąpi. Log
jest trwały, bo to on jest raportem.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

ALERT_COST_ORDER_EXHAUSTED = "cost_order_exhausted"
ALERT_DRAFT_CONSULTANT_UNASSIGNED = "draft_consultant_unassigned"
ALERT_MD_BUDGET_LOW = "md_budget_low"
ALERT_MISSING_REVENUE_RATE = "missing_revenue_rate"

DL_ALERT_TYPES: tuple[str, ...] = (
    ALERT_COST_ORDER_EXHAUSTED,
    ALERT_DRAFT_CONSULTANT_UNASSIGNED,
    ALERT_MD_BUDGET_LOW,
    ALERT_MISSING_REVENUE_RATE,
)

DL_ALERT_TYPE_LABELS: dict[str, str] = {
    ALERT_COST_ORDER_EXHAUSTED: "Zamówienie kosztowe wyczerpane",
    ALERT_DRAFT_CONSULTANT_UNASSIGNED: "Konsultant bez zamówienia (Draft)",
    ALERT_MD_BUDGET_LOW: "Niski poziom MD na zamówieniu",
    ALERT_MISSING_REVENUE_RATE: "Brak stawki przychodowej",
}

DL_ALERT_STATUS_NEW = "new"
DL_ALERT_STATUS_HANDLED = "handled"
DL_ALERT_STATUSES: tuple[str, ...] = (DL_ALERT_STATUS_NEW, DL_ALERT_STATUS_HANDLED)

DL_ALERT_STATUS_LABELS: dict[str, str] = {
    DL_ALERT_STATUS_NEW: "Nowe",
    DL_ALERT_STATUS_HANDLED: "Obsłużone",
}


class DlAlert(Base):
    """Jeden alert dla jednego Delivery Leada."""

    __tablename__ = "dl_alerts"
    __table_args__ = (
        CheckConstraint(
            "alert_type IN ('cost_order_exhausted', "
            "'draft_consultant_unassigned', 'md_budget_low', "
            "'missing_revenue_rate')",
            name="ck_dl_alerts_type",
        ),
        CheckConstraint("status IN ('new', 'handled')", name="ck_dl_alerts_status"),
        # „Obsłużone" bez znacznika czasu nie da się odróżnić od wiersza
        # sprzed wprowadzenia tej kolumny, a czas reakcji jest treścią raportu.
        CheckConstraint(
            "status <> 'handled' OR handled_at IS NOT NULL",
            name="ck_dl_alerts_handled_coherence",
        ),
        UniqueConstraint("dedupe_key", name="uq_dl_alerts_dedupe_key"),
        Index(
            "ix_dl_alerts_open",
            "user_id",
            "created_at",
            postgresql_where=text("status = 'new'"),
        ),
        Index(
            "ix_dl_alerts_rule_scope",
            "alert_type",
            "user_id",
            "client_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    alert_type: Mapped[str] = mapped_column(String(48), nullable=False)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    """Odbiorca. Jeden warunek daje tyle wierszy, ilu DL jest przypisanych do
    klienta — raport jest per osoba, a nie per zdarzenie."""

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    order_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_order_groups.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_orders.id", ondelete="SET NULL"), nullable=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=DL_ALERT_STATUS_NEW
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    handled_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    handled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    recipient = relationship("User", foreign_keys=[user_id])
    handler = relationship("User", foreign_keys=[handled_by_user_id])
    client = relationship("Client", foreign_keys=[client_id])
    order_group = relationship("ClientOrderGroup", foreign_keys=[order_group_id])
    order = relationship("ClientOrder", foreign_keys=[order_id])

    def __repr__(self) -> str:
        return (
            f"<DlAlert id={self.id} type={self.alert_type!r} "
            f"user={self.user_id} status={self.status!r}>"
        )
