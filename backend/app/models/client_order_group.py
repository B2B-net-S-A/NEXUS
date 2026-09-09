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
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


GROUP_STATUS_DRAFT = "draft"
GROUP_STATUS_ACTIVE = "active"
GROUP_STATUS_SCHEDULED = "scheduled"
GROUP_STATUS_COMPLETED = "completed"
GROUP_STATUS_EXHAUSTED = "exhausted"
GROUP_STATUSES: tuple[str, ...] = (
    GROUP_STATUS_DRAFT,
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_SCHEDULED,
    GROUP_STATUS_COMPLETED,
    GROUP_STATUS_EXHAUSTED,
)

GROUP_STATUS_LABELS: dict[str, str] = {
    GROUP_STATUS_DRAFT: "Draft",
    GROUP_STATUS_ACTIVE: "Aktywne",
    GROUP_STATUS_SCHEDULED: "Przyszłe",
    GROUP_STATUS_COMPLETED: "Zakończone",
    GROUP_STATUS_EXHAUSTED: "Wyczerpane",
}


class ClientOrderGroup(Base, TimestampMixin):
    """Zamówienie od klienta obejmujące jedną lub wiele linii konsultantów."""

    __tablename__ = "client_order_groups"
    __table_args__ = (
        CheckConstraint(
            "md_budget_mode IS NULL OR (order_type = 'md' AND ((md_budget_mode = 'shared' AND is_md_budget_based = TRUE) OR (md_budget_mode = 'per_person' AND is_md_budget_based = FALSE)))",
            name="ck_client_order_groups_md_mode",
        ),
        CheckConstraint(
            "order_type IS NULL OR order_type IN ('cost', 'md')",
            name="ck_client_order_groups_order_type",
        ),
        CheckConstraint(
            # Schemat pilnuje spójności typu z flagami i NIC WIĘCEJ. Do 0263
            # ten więz kodował też `client_id IN (155, 38339)`, czyli
            # rozstrzygał w bazie, kto jest Lotte Wedel i Cyfrowym Polsatem —
            # a tożsamość tych klientów aplikacja traktuje jako podmienialną
            # (autouse fixture w `tests/conftest.py` odpina bramki, żeby
            # 155. testowy klient nie dostał cudzej polityki). Baza nie
            # widziała tej podmiany, więc oba źródła prawdy się rozjeżdżały
            # i zapis kończył się 500 w środku aktywacji szkicu.
            #
            # Reguła „wspólną pulę MD mają wyłącznie CP i Lotte Wedel" żyje
            # w aplikacji, w obu miejscach zapisu: dwa jawne 422
            # w `api/client_order_groups.py` oraz wyprowadzenie flagi
            # z `client_uses_shared_md_pool` w `order_group_materializer`.
            "order_type IS NULL OR "
            "(order_type = 'cost' AND is_cost_based = TRUE "
            "AND is_md_budget_based = FALSE) OR "
            "(order_type = 'md' AND is_cost_based = FALSE)",
            name="ck_client_order_groups_explicit_type_coherence",
        ),
        CheckConstraint(
            "end_date IS NULL OR end_date >= start_date",
            name="ck_client_order_groups_dates",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'scheduled', 'completed', 'exhausted')",
            name="ck_client_order_groups_status",
        ),
        # Zamówienie kosztowe jest albo kompletne, albo go nie ma. Kwota bez
        # reszty (albo odwrotnie) wysadza odejmowanie w środku transakcji
        # importu, a kwota <= 0 nie jest budżetem.
        CheckConstraint(
            "("
            "is_cost_based = FALSE AND budget_amount IS NULL "
            "AND budget_remaining IS NULL"
            ") OR ("
            "is_cost_based = TRUE AND budget_amount IS NOT NULL "
            "AND budget_amount > 0 AND budget_remaining IS NOT NULL"
            ")",
            name="ck_client_order_groups_cost_coherence",
        ),
        CheckConstraint(
            "NOT (is_cost_based = TRUE AND is_md_budget_based = TRUE)",
            name="ck_client_order_groups_settlement_exclusive",
        ),
        # Wspólna pula MD jest kompletna albo nie istnieje. Dotychczasowe
        # zamówienia MD mają budżety na liniach i pozostają w trzecim stanie:
        # oba booleany FALSE, wszystkie pola wspólnej puli NULL/0.
        CheckConstraint(
            "("
            "is_md_budget_based = FALSE AND md_budget_total IS NULL "
            "AND md_budget_remaining IS NULL AND md_budget_manual_adjustment = 0"
            ") OR ("
            "is_md_budget_based = TRUE AND md_budget_total IS NOT NULL "
            "AND md_budget_total > 0 AND md_budget_remaining IS NOT NULL "
            "AND md_budget_remaining >= 0"
            ")",
            name="ck_client_order_groups_md_budget_coherence",
        ),
        CheckConstraint(
            "status <> 'completed' OR closure_date IS NOT NULL",
            name="ck_client_order_groups_closure",
        ),
        Index("ix_client_order_groups_client", "client_id"),
        Index("ix_client_order_groups_status", "client_id", "status"),
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

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=GROUP_STATUS_ACTIVE
    )
    """``active`` | ``scheduled`` | ``completed`` | ``exhausted``.

    Stan jest PRZECHOWYWANY, a nie wyliczany z dat — data nie odróżnia
    zamówienia domkniętego świadomie („konsultant odchodzi") od takiego,
    któremu po prostu minął termin, a te dwie sytuacje prowadzą do różnych
    działań. ``exhausted`` dochodzi automatycznie, gdy budżet kosztowy albo
    wspólna pula MD zejdzie do zera; różni się od ``completed`` tym, że nie da
    się go cofnąć zwykłym przywróceniem (trzeba skorygować budżet)."""

    closure_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    closure_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    order_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    """Jawny typ nowych grup: ``cost`` albo ``md``.

    Okresowe zamówienia pozostają samodzielnymi ``ClientOrder``. ``NULL``
    oznacza grupę historyczną, której zachowanie wyznaczają istniejące flagi i
    polityki klientowe; migracja nie klasyfikuje jej wstecz.
    """
    md_budget_mode: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    """Explicit choice for new MD orders; NULL preserves historical behavior."""
    md_budget_mode_locked: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    is_cost_based: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    """Zamówienie rozliczane KWOTĄ, nie liczbą MD (Polkomtel).

    Kwota mieszka na grupie, bo to jedna pula dzielona przez kilku
    konsultantów. Trzymanie jej per linia wymagałoby podziału budżetu z góry —
    czego nikt nie robi — i uniemożliwiłoby odpowiedź na jedyne pytanie, które
    tu ma znaczenie: ile jeszcze zostało na całym zamówieniu."""

    budget_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(17, 3), nullable=True
    )
    """Kwota wyjściowa — niezmienna w toku zwykłej pracy, do wglądu."""

    budget_remaining: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(17, 3), nullable=True
    )
    """WYLICZANE: ``budget_amount - Σ rozliczonych faktur + korekta``.

    Nie schodzi poniżej zera — nadwyżka nad budżetem zostaje zapisana jako
    ``unsettled_amount`` na konkretnym wierszu konsumpcji, żeby dało się
    powiedzieć, KTÓREJ osobie zabrakło pieniędzy, a nie tylko że zabrakło."""

    budget_manual_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(17, 3), nullable=False, server_default="0"
    )
    """Ręczna korekta trzymana OSOBNO od konsumpcji — dokładnie z tego samego
    powodu co ``ClientOrder.md_manual_adjustment``: korekta nadpisująca
    ``budget_remaining`` wprost przeżyłaby do najbliższego importu, który
    przelicza resztę od ``budget_amount`` i skasowałby ją po cichu."""

    is_md_budget_based: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    """Klientowo ograniczona, wspólna pula MD całego zamówienia.

    Zwykły jawny ``order_type='md'`` nie ustawia tej flagi: jego budżet mieszka
    na każdej linii konsultanta. ``True`` jest wyłącznie świadomym wariantem
    Cyfrowego Polsatu i Lotte Wedel, także dla nowo tworzonych zamówień.
    """

    md_budget_total: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(16, 6), nullable=True
    )
    md_budget_remaining: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(16, 6), nullable=True
    )
    """Pozostała wspólna pula; przeliczana od zera i nigdy ujemna."""

    md_budget_manual_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(16, 6), nullable=False, server_default="0"
    )
    """Jawna korekta wspólnej puli, niezależna od miesięcznej konsumpcji."""

    predecessor_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_order_groups.id", ondelete="SET NULL"), nullable=True
    )
    """Zamówienie, które to przedłuża. ``SET NULL`` — usunięcie poprzednika nie
    może kasować jego kontynuacji."""

    # Master PDF zamówienia wielo-konsultantowego. Każdy przypisany kontrakt
    # dostaje własną kopię ``ContractDocument``; master pozwala dosynchronizować
    # dokument osobie dodanej później i podmienić wszystkie istniejące kopie.
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_uploaded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    file_uploaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    client = relationship("Client")
    creator = relationship("User", foreign_keys=[created_by_user_id])
    closer = relationship("User", foreign_keys=[closed_by_user_id])
    file_uploader = relationship("User", foreign_keys=[file_uploaded_by])
    predecessor = relationship(
        "ClientOrderGroup", remote_side=[id], foreign_keys=[predecessor_group_id]
    )
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
    md_consumptions = relationship(
        "ClientOrderGroupMdConsumption",
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ClientOrderGroupMdConsumption.period_month.asc()",
    )

    def __repr__(self) -> str:
        return (
            f"<ClientOrderGroup id={self.id} client={self.client_id} "
            f"number={self.order_number!r}>"
        )


class ClientOrderGroupMdConsumption(Base, TimestampMixin):
    """Miesięczne zużycie wspólnej puli MD jednego zamówienia."""

    __tablename__ = "client_order_group_md_consumptions"
    __table_args__ = (
        CheckConstraint(
            "period_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'",
            name="ck_group_md_consumptions_period",
        ),
        CheckConstraint(
            "source IN ('import', 'manual')",
            name="ck_group_md_consumptions_source",
        ),
        CheckConstraint(
            "md_reported >= 0",
            name="ck_group_md_consumptions_nonnegative",
        ),
        Index(
            "ux_group_md_consumptions_group_month",
            "group_id",
            "period_month",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("client_order_groups.id", ondelete="CASCADE"), nullable=False
    )
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    md_reported: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    group = relationship("ClientOrderGroup", back_populates="md_consumptions")
    author = relationship("User", foreign_keys=[created_by_user_id])


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
            "'zamiana_kontraktora', 'edycja_reczna', 'zakonczenie', "
            "'przywrocenie', 'wyczerpanie', 'przedluzenie', 'import_faktur', "
            "'transfer_md', 'zakonczenie_konsultanta', 'decyzja_md_wymagana', "
            "'usuniecie_puli_md', 'przeniesienie_puli_md', "
            "'przywrocenie_konsultanta')",
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
