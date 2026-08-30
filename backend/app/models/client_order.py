"""Order (Zamówienie od klienta) — perspektywa klienta z konkretnej rekrutacji.

Model biznesowy body-leasingu:
- Order = jeden PDF zamówienia od klienta (kontraktor, stanowisko, rate_client,
  daty)
- ZAWSZE pod konkretnym kandydackim ``Contract`` (1:N — jeden Contract ma wiele
  Orderów w czasie, np. przedłużenia 3msc → 6msc → 6msc)
- Pochodzi z konkretnego ``Job`` (rekrutacji) — `job_id` nullable bo dla
  legacy/ad-hoc orderów może brakować
- Może być bez MSA (`framework_contract_id` nullable)

Marża per Order = `rate_client - Contract.rate_candidate` (rate_candidate trzymany
na Contract; Order może mieć różny rate_client niż Contract.rate_client — np.
przedłużenie z podwyżką).
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.contract import RateUnit


class ClientOrderStatus(str, enum.Enum):
    """Lifecycle order/zamówienia."""

    draft = "draft"  # Auto-utworzony z hired hook lub manualnie, do uzupełnienia
    active = "active"  # Aktywne, kontraktor pracuje
    paused = "paused"  # Tymczasowo wstrzymane
    completed = "completed"  # Zakończone (end_date minęło lub kontraktor odszedł)
    cancelled = "cancelled"  # Anulowane przed startem


class ClientOrder(Base, TimestampMixin):
    """Zamówienie od klienta pod konkretnym kandydackim Contractem."""

    __tablename__ = "client_orders"
    __table_args__ = (
        CheckConstraint(
            "order_type IS NULL OR order_type IN ('periodic', 'cost', 'md')",
            name="ck_client_orders_order_type",
        ),
        CheckConstraint(
            "project_part IS NULL OR project_part IN "
            "('cz1', 'cz2', 'cz4', 'cz5', 'cz6')",
            name="ck_client_orders_project_part",
        ),
        # Budżet MD jest albo kompletny, albo go nie ma. Częściowo wypełniony
        # (budżet bez stawki przychodowej) wysadziłby dzielenie przy zamianie
        # kontraktora w środku transakcji; stawka <= 0 jest dzielnikiem, więc
        # baza odrzuca ją niezależnie od tego, co przepuści API.
        #
        # Odwrotność NIE obowiązuje: linia zamówienia KOSZTOWEGO ma obie
        # stawki i nie ma budżetu MD (pula jest wspólna i mieszka na
        # zamówieniu). Do 0233 pierwszy człon wymagał tu `md_rate_revenue IS
        # NULL` i taka linia po prostu nie dawała się zapisać.
        CheckConstraint(
            "("
            "("
            "md_total IS NULL AND md_remaining IS NULL AND md_input_mode IS NULL "
            "AND md_input_value IS NULL"
            ") OR ("
            "md_total IS NOT NULL AND md_remaining IS NOT NULL "
            "AND md_input_mode IN ('md', 'amount') AND md_input_value IS NOT NULL "
            "AND md_rate_revenue IS NOT NULL AND md_rate_revenue > 0"
            ")"
            ") AND (md_rate_revenue IS NULL OR md_rate_revenue > 0)",
            name="ck_client_orders_md_coherence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    """FK do kandydackiego Contract. Order ZAWSZE należy do jednego Contractu."""

    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    """Z której rekrutacji to zamówienie wzięło (nullable dla legacy)."""

    framework_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    """MSA pod którą jest Order. Nullable bo klient może nie mieć MSA."""

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[ClientOrderStatus] = mapped_column(
        Enum(ClientOrderStatus, name="clientorderstatus", create_type=False),
        nullable=False,
        default=ClientOrderStatus.draft,
        server_default="draft",
        index=True,
    )

    order_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    """Jawny typ wyłącznie dla zamówień utworzonych po wdrożeniu selektora.

    ``NULL`` jest stanem legacy i celowo nie jest uzupełniany migracją. Dzięki
    temu stare zamówienia nadal przechodzą przez dotychczasową logikę klientową
    i dopasowanie arkuszy, a nowe mają jednoznaczny typ niezależny od klienta.
    """

    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Plan analytics PR 6: FAKT pierwszej aktywacji zamówienia (nie estymata).
    # Ustawiane raz — przy utworzeniu ze statusem active albo pierwszym
    # przejściu na active. Historyczne zamówienia sprzed migracji 0176 mają
    # NULL → raporty czasu wypełnienia oznaczają je jako partial, NIGDY nie
    # zgadują daty.
    filled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    """``NULL`` = open-ended. Indeksowane — scheduler skanuje expiry."""

    # Stawki są snapshotem warunków TEGO zamówienia. Mogą różnić się od
    # bieżącego Contract przy przedłużeniu albo po ręcznej korekcie zamówienia.
    # Do 0249 koszt był czytany i edytowany wprost na Contract, przez co zmiana
    # jednostki/waluty jednego zamówienia przepisywała wszystkie pozostałe.
    # Numeric(12,3) — stawka klienta z PO może być dziesiętna z 3 miejscami
    # po przecinku (np. Alior 164.375 PLN/h — migracja 0149).
    rate_client: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 3), nullable=True
    )
    rate_candidate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 3), nullable=True
    )

    # Jedna jednostka opisuje obie stawki zamówienia. Snapshot jest konieczny:
    # późniejsza zmiana Contract nie może przepisać historii ani ręcznego
    # wyboru w pojedynczym zamówieniu. Linie grupowe nadal przechowują
    # kanoniczne stawki w md_rate_* (PLN/MD); dla nich ten snapshot ma wartość
    # daily i nie zmienia arytmetyki budżetów.
    rate_unit: Mapped[RateUnit] = mapped_column(
        Enum(RateUnit, name="rateunit", create_type=False),
        nullable=False,
        default=RateUnit.monthly,
        server_default="monthly",
    )
    billing_hours_per_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=160, server_default="160"
    )

    # Waluty obu stron stawki. ``currency`` niżej zostaje aliasem strony
    # przychodowej dla zgodności starszych integracji.
    rate_client_currency: Mapped[Optional[str]] = mapped_column(
        String(3), nullable=True
    )
    rate_candidate_currency: Mapped[Optional[str]] = mapped_column(
        String(3), nullable=True
    )

    total_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    """Całkowita wartość kontraktu (rate_client × długość okresu) — calculated
    lub manualnie wpisane."""

    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)

    # „Część umowy" Centrum e-Zdrowia (ticket #3): slug cz1|cz2|cz4|cz5|cz6
    # (cz.3 celowo nie istnieje). Nullable — wymagane tylko w walidacji API/UI
    # dla client_id=115 (app/services/ezdrowie.py); inni klienci mają NULL.
    project_part: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    # PO PDF (Purchase Order od klienta)
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Kto i kiedy wgrał TEN plik — celowo osobno od ``created_by_user_id``,
    # bo zamówienie i jego PDF powstają w różnych momentach i zwykle z ręki
    # różnych osób (drafty tworzy automat z hooka „hired", plik dokłada
    # człowiek później). Sekcja „Dokumenty zamówień" w zakładce Dokumenty
    # kontraktu pokazuje tę atrybucję w kolumnie „Dodał" — jak każdy inny
    # dokument kontraktu (``contract_documents.uploaded_by``).
    file_uploaded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    file_uploaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Linia zamówienia wielo-konsultantowego (migracja 0227) ────────────
    # Wypełnione TYLKO dla klientów rozliczanych w T&M na MD (BIK, Polkomtel,
    # BNP — lista w MULTI_CONSULTANT_ORDER_CLIENT_IDS). U pozostałych klientów
    # wszystkie te pola są NULL i nic się dla nich nie zmienia.
    order_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_order_groups.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    """Zamówienie klienta („nr 445"), pod którym ta osoba pracuje."""

    # Stawki są PER MD (osobodzień) i celowo NIE nadpisują `rate_client` /
    # `Contract.rate_candidate`: tamte są interpretowane przez
    # `Contract.rate_unit` (h/dzień/mc) i zasilają marżę miesięczną w widokach
    # jednoosobowych. Wpisanie tu stawki dziennej do pola czytanego jako
    # miesięczne dałoby cichy, 22-krotny błąd marży u trzech klientów.
    md_rate_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    md_rate_revenue: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    md_input_mode: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    """``md`` albo ``amount`` — czy operator podał liczbę MD, czy kwotę."""

    md_input_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(16, 6), nullable=True
    )
    """Wartość wpisana przez operatora, zachowana dosłownie. Bez niej nie da
    się później pokazać, czy budżet 41,67 MD wziął się z „41,67 MD", czy
    z „50 000 zł" — a to różnica przy negocjacji aneksu."""

    # Numeric(16, 6): `md_total = kwota / stawka` bywa ułamkiem nieskończonym,
    # więc „bez zaokrąglenia" jest nieosiągalne w typie stałoprzecinkowym.
    # Sześć miejsc to cztery miejsca zapasu ponad prezentację (2 miejsca).
    md_total: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6), nullable=True)
    md_remaining: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(16, 6), nullable=True
    )
    """WYLICZANE: ``md_total - Σ konsumpcji + md_manual_adjustment``. Może zejść
    do zera i poniżej — przekroczony budżet jest faktem handlowym, więc UI go
    sygnalizuje kolorem, ale nic go nie blokuje ani nie ścina."""

    md_manual_adjustment: Mapped[Decimal] = mapped_column(
        Numeric(16, 6), nullable=False, server_default="0"
    )
    """Ręczna korekta operatora, trzymana OSOBNO od konsumpcji. Gdyby korekta
    nadpisywała `md_remaining` wprost, najbliższy import miesiąca przeliczyłby
    pozostałość od `md_total` i skasował ją po cichu."""

    predecessor_order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_orders.id", ondelete="SET NULL"), nullable=True
    )
    """Linia, z której ta powstała przy zamianie kontraktora."""

    # Relationships
    client = relationship("Client", backref="orders")
    order_group = relationship("ClientOrderGroup", back_populates="lines")
    predecessor = relationship(
        "ClientOrder", remote_side=[id], foreign_keys=[predecessor_order_id]
    )
    md_consumptions = relationship(
        "ClientOrderMdConsumption",
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ClientOrderMdConsumption.period_month.asc()",
    )
    invoice_consumptions = relationship(
        "ClientOrderInvoiceConsumption",
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ClientOrderInvoiceConsumption.period_month.asc()",
    )
    contract = relationship("Contract", back_populates="client_orders")
    job = relationship("Job", foreign_keys=[job_id])
    framework_contract = relationship(
        "ClientFrameworkContract", back_populates="orders"
    )
    creator = relationship("User", foreign_keys=[created_by_user_id])
    file_uploader = relationship("User", foreign_keys=[file_uploaded_by])

    def __repr__(self) -> str:
        return (
            f"<ClientOrder id={self.id} client={self.client_id} "
            f"contract={self.contract_id} title={self.title!r} status={self.status}>"
        )
