"""Grupa zamówień klienta = jedno „Zamówienie nr 445" obejmujące kilku konsultantów.

Klient rozliczany w T&M na MD (BIK, Polkomtel, BNP) przysyła jeden numer
zamówienia, pod którym pracuje kilka osób — każda z własną stawką i własnym
budżetem MD. W NEXUSIE każda z tych osób ma już swoje ``ClientOrder`` pod
swoim ``Contract``, więc grupa jest warstwą NAD nimi, a nie zamiast nich.

Dzięki temu zamówienie konsultanta z takiej grupy nadal ma kontrakt, więc
nadal trafia do skanera wygasania, syncu terminacji, rejestru kontraktów i
MRR — dokładnie tak samo jak zamówienie jednoosobowe. Pełne uzasadnienie
wyboru: docstring migracji ``0227_multi_consultant_orders``.

Zamówienia pozostałych klientów mają ``order_group_id IS NULL`` i nie wiedzą
o istnieniu tego modelu.
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
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ClientOrderGroup(Base, TimestampMixin):
    """Zamówienie od klienta obejmujące jedną lub wiele linii konsultantów."""

    __tablename__ = "client_order_groups"
    __table_args__ = (
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_client_order_groups_dates",
        ),
        Index("ix_client_order_groups_client", "client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    order_number: Mapped[str] = mapped_column(String(64), nullable=False)
    """Numer nadany przez klienta („445"). Świadomie BEZ unikalności w bazie —
    ten sam numer potrafi wrócić w kolejnym roku, a twarde ograniczenie
    zablokowałoby wtedy poprawny zapis. Duplikat sygnalizuje API ostrzeżeniem."""

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    """``NULL`` = bezterminowo (ta sama semantyka co ``ClientOrder.end_date``)."""

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    client = relationship("Client")
    creator = relationship("User", foreign_keys=[created_by_user_id])
    lines = relationship(
        "ClientOrder",
        back_populates="order_group",
        # BEZ cascade delete-orphan: usunięcie grupy nie może kasować zamówień
        # konsultantów. Zamówienie to realne zaangażowanie z kontraktem,
        # notatkami i plikiem PO — grupa jest tylko spinaczem numeru klienta.
        order_by="ClientOrder.start_date.asc().nullsfirst()",
        viewonly=False,
    )
    events = relationship(
        "ClientOrderGroupEvent",
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ClientOrderGroupEvent.created_at.desc()",
    )

    def __repr__(self) -> str:
        return (
            f"<ClientOrderGroup id={self.id} client={self.client_id} "
            f"number={self.order_number!r}>"
        )


class ClientOrderGroupEvent(Base):
    """Dziennik zdarzeń zamówienia — „Historia zamówienia" w interfejsie.

    Nie jest ozdobą. Zamiana kontraktora przelicza MD nowej linii i zostawia
    starą z liczbą MD pozostałą na dzień zamiany; bez zapisu OBU stawek, OBU
    liczb MD i daty zamiany nie da się później rozliczyć faktury za miesiąc,
    w którym doszło do zamiany (MD sprzed zamiany idą po stawce poprzednika).
    Te dane trafiają do ``payload``, a ``description`` niesie ten sam fakt po
    polsku, dla człowieka.
    """

    __tablename__ = "client_order_group_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('utworzenie', 'dodanie_konsultanta', 'import_md', "
            "'zamiana_kontraktora', 'edycja_reczna')",
            name="ck_client_order_group_events_type",
        ),
        Index("ix_client_order_group_events_group", "group_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    group_id: Mapped[int] = mapped_column(
        ForeignKey("client_order_groups.id", ondelete="CASCADE"), nullable=False
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_orders.id", ondelete="SET NULL"), nullable=True
    )
    """Linia, której dotyczy zdarzenie. ``SET NULL``, nie ``CASCADE`` — wpis
    „konsultant X został zamieniony" ma przeżyć usunięcie samej linii."""

    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    group = relationship("ClientOrderGroup", back_populates="events")
    author = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self) -> str:
        return (
            f"<ClientOrderGroupEvent id={self.id} group={self.group_id} "
            f"type={self.event_type!r}>"
        )
