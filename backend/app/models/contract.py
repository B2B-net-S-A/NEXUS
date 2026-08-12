import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ContractType(str, enum.Enum):
    b2b = "b2b"
    uop = "uop"  # Umowa o pracę
    uzlecenie = "uzlecenie"  # Umowa zlecenie


class ContractStatus(str, enum.Enum):
    draft = "draft"
    # Draft finalized into an immutable snapshot and waiting for a qualified
    # signature. A NON-active gate: an unsigned contract may never skip straight
    # to `active` — it lands here first (see ``app.services.contract_lifecycle``).
    ready_for_signature = "ready_for_signature"
    active = "active"
    ending = "ending"  # < 30 dni do końca
    ended = "ended"
    # Soft-deleted / annulled. Terminal. Used instead of a hard DELETE for
    # executed contracts so documents + signature evidence are preserved.
    void = "void"


class RateUnit(str, enum.Enum):
    hourly = "hourly"
    daily = "daily"
    monthly = "monthly"


class ContractWorkMode(str, enum.Enum):
    remote = "remote"
    hybrid = "hybrid"
    onsite = "onsite"


class ProlongationStatus(str, enum.Enum):
    """Czy kontrakt zostanie przedłużony (forecast renewalu).

    Napędza per-klient rejestr kontraktów (np. Nordea) — pozwala filtrować
    kontrakty po prawdopodobieństwie przedłużenia i planować rozmowy.
    """

    unknown = "unknown"  # jeszcze nie wiadomo / nie pytano
    yes = "yes"  # klient potwierdził przedłużenie
    no = "no"  # nie będzie przedłużenia (projekt się kończy)
    negotiate = "negotiate"  # w trakcie negocjacji warunków


class EngagementModel(str, enum.Enum):
    """Model rozliczenia kontraktu — różni się per klient.

    * ``time_based`` — klasyczny czasowy (start_date → end_date).
    * ``hours_pool`` — pula godzin do wykorzystania (np. wsparcie ad-hoc):
      ``hours_pool_total`` budżet, ``hours_pool_consumed`` zużyte.
    """

    time_based = "time_based"
    hours_pool = "hours_pool"


class OrderConsumptionUnit(str, enum.Enum):
    """Jednostka zużycia zamówienia — RBH (roboczogodziny) lub MD (mandays).

    Klienci rozliczający się per-zamówienie (np. BNP, BIK, Polkomtel, Bosch)
    raportują zużycie zamówienia w roboczogodzinach lub w osobodniach.
    """

    rbh = "rbh"  # roboczogodziny (man-hours)
    md = "md"  # mandays / osobodni (man-days)


class ContractTerminationReason(str, enum.Enum):
    """Structured reasons for ending cooperation — drives attrition analytics."""

    poached_by_client = "poached_by_client"
    project_ended = "project_ended"
    client_budget_cut = "client_budget_cut"
    performance_issue = "performance_issue"
    consultant_resigned = "consultant_resigned"
    better_offer = "better_offer"
    personal_reasons = "personal_reasons"
    contract_breach = "contract_breach"
    mutual_agreement = "mutual_agreement"
    other = "other"


class Contract(Base, TimestampMixin):
    """
    Kontrakt body-leasingowy — łączy kandydata z klientem przez ofertę.
    Marża obliczana automatycznie: rate_client - rate_candidate.
    """

    __tablename__ = "contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Strony kontraktu
    #
    # `SET NULL`, nie `CASCADE` (migracja 0225): usunięcie kandydata z bazy
    # rekrutacyjnej nie może kasować umowy, bo na umowie wiszą `invoices`,
    # `document_signatures` i `client_orders` — dokumenty księgowe i dowodowe,
    # które nie mają własnego FK na kandydata i poszłyby razem z nią.
    # Stąd kolumna jest nullowalna: NULL = umowa odpięta od usuniętej osoby.
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Pseudonimowy klucz podmiotu, stemplowany w momencie usuwania kandydata.
    # Po wyzerowaniu FK nic nie wiązałoby ze sobą faktur tej samej osoby, więc
    # księgowość nie mogłaby uzgodnić rozrachunków. Kluczowany HMAC (ten sam
    # klucz co fingerprint tożsamości) łączy dokumenty bez przywracania danych
    # osobowych. NULL dla umów żyjących kandydatów.
    candidate_subject_ref: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id"), nullable=False, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), index=True)

    # Daty
    # Nullable — kontrakt może powstać z zamówienia bez znanej daty "od".
    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(Date)

    # Stawki finansowe — Numeric(12,3): stawki godzinowe bywają z groszami/
    # połówką (np. klient VeloBank 206.25, kandydat Erste 157.5) lub z trzecim
    # miejscem po przecinku (np. Alior 164.375 / 141.175 zł/h — migracja 0149).
    rate_candidate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    rate_client: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))
    # Stawka z umowy ramowej (MSA) — wartość referencyjna uzgodniona w umowie
    # ramowej z klientem. NIE wchodzi do liczenia marży (to baseline/ceiling).
    # Numeric(12,2): stawki ramowe bywają z groszami (np. 215,60) — Integer
    # odrzucał je 422-ką na schemacie (migracja 0157).
    framework_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="PLN")

    # Jednostka stawki (godz. / dzień / mies.) + liczba godzin billingowych (dla stawki godzinowej).
    rate_unit: Mapped[RateUnit] = mapped_column(
        Enum(RateUnit, name="rateunit"),
        default=RateUnit.monthly,
        nullable=False,
        server_default="monthly",
    )
    billing_hours_per_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=160, server_default="160"
    )

    # Marża — obliczana automatycznie (rate_client - rate_candidate).
    # Numeric(12,3) bo stawki mogą mieć do 3 miejsc po przecinku (migracja 0149).
    margin: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 3))

    contract_type: Mapped[ContractType] = mapped_column(
        Enum(ContractType), default=ContractType.b2b, nullable=False
    )

    status: Mapped[ContractStatus] = mapped_column(
        Enum(ContractStatus), default=ContractStatus.draft, nullable=False, index=True
    )

    # Załączniki/dokumenty (lista URL lub metadanych)
    documents: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)

    # Assignment / deployment context (Phase 9 B5) — gdzie i pod kim kontraktor pracuje.
    client_pm_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_pm_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # FK do Contact dla PM po stronie klienta (migracja 0097, 2026-05-11).
    # client_pm_name/email zostają jako fallback dla starych kontraktów bez
    # zlinkowanego Contact. Po utworzeniu Contact'u DL może manualnie zlinkować.
    client_pm_contact_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    work_mode: Mapped[Optional[ContractWorkMode]] = mapped_column(
        Enum(ContractWorkMode, name="contractworkmode"), nullable=True
    )
    # Line manager po stronie klienta — osoba, pod którą raportuje kontraktor
    # (odrębna rola od `client_pm_name`, który jest PM-em projektu).
    line_manager: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    office_location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    team_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    project_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Free-form internal handover notes (C6) — widoczne tylko dla TAC/delivery.
    handover_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Structured termination metadata — populated when status flips to `ended`.
    # `terminated_at` may differ from `end_date` (e.g. early termination).
    # `termination_lessons` is a TAC-only free-form "what would we do differently".
    termination_reason: Mapped[Optional[ContractTerminationReason]] = mapped_column(
        Enum(ContractTerminationReason, name="contractterminationreason"),
        nullable=True,
        index=True,
    )
    termination_lessons: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    terminated_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    # Soft-delete / void metadata — populated when status flips to `void` via
    # the lifecycle service. A void keeps documents + signature evidence (unlike
    # a hard DELETE), so an executed contract stays auditable after annulment.
    voided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    voided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Desired rate range we want to achieve on this contract (used by benchmark
    # comparison and by sales during renegotiation). Numeric(12,2) — grosze jak
    # w framework_rate (migracja 0157).
    target_rate_min: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    target_rate_max: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    # End of the client's purchase order — often earlier than our contract with
    # the consultant. Drives proactive reminders so we can react before the
    # order lapses.
    client_order_end_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
    )

    # ── Per-klient rejestr kontraktów (migracja 0138) ─────────────────────
    # Numer/kod projektu po stronie klienta (np. wewnętrzny ID projektu w
    # Nordea) — osobny od naszego `id`. `project_name` istnieje już wyżej.
    project_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Status przedłużenia (renewal forecast) — domyślnie "nieznany".
    prolongation_status: Mapped[ProlongationStatus] = mapped_column(
        Enum(ProlongationStatus, name="prolongationstatus"),
        default=ProlongationStatus.unknown,
        nullable=False,
        server_default="unknown",
        index=True,
    )

    # Model rozliczenia: czasowy vs pula godzin. Per kontrakt — jeden klient
    # może mieć oba (np. Nordea: część czasowa, część godzinowa).
    engagement_model: Mapped[EngagementModel] = mapped_column(
        Enum(EngagementModel, name="engagementmodel"),
        default=EngagementModel.time_based,
        nullable=False,
        server_default="time_based",
    )
    # Pula godzin — tylko gdy engagement_model == hours_pool.
    hours_pool_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hours_pool_consumed: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, server_default="0"
    )

    # ── Zużycie zamówienia (migracja 0144) ────────────────────────────────
    # Ilość zużyta z zamówienia klienta wraz z jednostką: RBH (roboczogodziny)
    # lub MD (osobodni). Wymagane przez klientów rozliczających się per-
    # zamówienie (BNP, BIK, Polkomtel, Bosch). Oba pola nullable — wypełniane
    # razem (ilość + jednostka) z formularza "Nowy kontrakt".
    order_consumption: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), nullable=True
    )
    order_consumption_unit: Mapped[Optional[OrderConsumptionUnit]] = mapped_column(
        Enum(OrderConsumptionUnit, name="orderconsumptionunit"), nullable=True
    )

    # ── Editable draft body (migracja 0058) ──────────────────────────────
    # Treść draftu umowy renderowana z `ContractTemplate.content_jinja` przy
    # pierwszym otwarciu zakładki "Umowa" w profilu kandydata, potem swobodnie
    # edytowana przez recruitera w Tiptap. Po finalizacji ląduje jako
    # `ContractDocument(doc_type=contract)` i status leci na `active`.
    draft_content_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    draft_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contract_templates.id", ondelete="SET NULL"), nullable=True
    )
    draft_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    draft_updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    candidate = relationship("Candidate", back_populates="contracts")
    client = relationship("Client", back_populates="contracts")
    job = relationship("Job", back_populates="contracts")
    documents_rel = relationship(
        "ContractDocument",
        back_populates="contract",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    equipment = relationship(
        "ContractEquipment",
        back_populates="contract",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ContractEquipment.created_at.desc()",
    )
    contract_notes = relationship(
        "Note",
        back_populates="contract",
        foreign_keys="Note.contract_id",
    )
    contract_calls = relationship(
        "Call",
        back_populates="contract",
        foreign_keys="Call.contract_id",
    )
    amendments = relationship(
        "ContractAmendment",
        back_populates="contract",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ContractAmendment.created_at.desc()",
    )
    # Effective-dated candidate-rate schedule (migracja 0144). Each row is a
    # step "rate od <effective_from>". The current candidate rate is derived
    # at read time via `effective_candidate_rate` — no background scheduler.
    candidate_rate_schedule = relationship(
        "ContractCandidateRate",
        back_populates="contract",
        cascade="all, delete-orphan",
        passive_deletes=True,
        # (effective_from, id): id makes same-day ties deterministic so the
        # newer step (higher id) loads last — the resolver's tiebreak and the
        # frontend's "(aktualna)" pick both rely on that order.
        order_by="ContractCandidateRate.effective_from, ContractCandidateRate.id",
    )
    # Effective-dated client-rate schedule (mirror of the candidate schedule).
    # Lets a future-dated `rate_change` amendment keep the old client rate until
    # it takes effect (old rate runs to the end of the current order; the new
    # rate applies from the amendment's effective_date). Current client rate is
    # derived at read time via `effective_client_rate` — no background job.
    client_rate_schedule = relationship(
        "ContractClientRate",
        back_populates="contract",
        cascade="all, delete-orphan",
        passive_deletes=True,
        # (effective_from, id): id makes same-day ties deterministic so the
        # newer step (higher id) loads last — mirror of candidate_rate_schedule.
        order_by="ContractClientRate.effective_from, ContractClientRate.id",
    )
    # Effective-dated framework-rate schedule ("stawka z umowy ramowej"). Lets a
    # planned MSA-rate change take effect only from its date. Informational only —
    # the framework rate never feeds the margin; the current value is derived at
    # read time via `effective_framework_rate` and cached into `framework_rate`.
    framework_rate_schedule = relationship(
        "ContractFrameworkRate",
        back_populates="contract",
        cascade="all, delete-orphan",
        passive_deletes=True,
        # (effective_from, id): id makes same-day ties deterministic so the
        # newer step (higher id) loads last — mirror of candidate_rate_schedule.
        order_by="ContractFrameworkRate.effective_from, ContractFrameworkRate.id",
    )
    onboarding_items = relationship(
        "ContractOnboardingItem",
        back_populates="contract",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ContractOnboardingItem.order",
    )
    invoices = relationship(
        "Invoice",
        back_populates="contract",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Invoice.issue_date.desc()",
    )
    # Klient-poziomowe zamówienia (Order = PDF od klienta z okresem/stawką).
    # 1 Contract ma N Orderów w czasie (np. przedłużenia 3msc → 6msc → 6msc
    # to 3 osobne Ordery pod 1 Contractem). Refactor 2026-05-11.
    client_orders = relationship(
        "ClientOrder",
        back_populates="contract",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ClientOrder.start_date.desc().nullslast()",
    )
    # Generator Umów B2B — dane per-umowa (1:1).
    b2b_detail = relationship(
        "B2BContractDetail",
        back_populates="contract",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @staticmethod
    def _as_decimal(value: object) -> Optional[Decimal]:
        """Coerce a rate (Decimal/int/float) to Decimal, tolerant of None.

        Stawki bywają mieszane typami: kolumny to ``Numeric`` (→ ``Decimal`` z
        bazy), ale schematy PATCH/CREATE przekazują ``float``/``int`` przed
        flush. ``Decimal - float`` rzuca ``TypeError`` (500), więc normalizujemy
        oba operandy do ``Decimal`` przez ``str`` (bez błędu binarnego floata).
        """
        if value is None:
            return None
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    def calculate_margin(self) -> Optional[Decimal]:
        """Oblicz marżę: stawka klienta - stawka kandydata (w tej samej jednostce)."""
        client = self._as_decimal(self.rate_client)
        candidate = self._as_decimal(self.rate_candidate)
        if client is not None and candidate is not None:
            return client - candidate
        return None

    @staticmethod
    def _resolve_scheduled_rate(
        schedule: object, on: date, fallback: Optional[Decimal]
    ) -> Optional[Decimal]:
        """Rate in effect on ``on`` from an effective-dated schedule.

        The step in effect wins: the latest ``effective_from <= on``, or — when
        every step is future-dated — the earliest upcoming one (so a fresh
        contract still has a rate). Ties on ``effective_from`` are broken by
        **insertion order: the last-added step wins**, so a same-day
        ``rate_change`` amendment supersedes the baseline seeded from the
        contract's start. That baseline shares ``effective_from`` with the new
        step exactly when the amendment's ``effective_date == start_date``;
        without this tiebreak the stale baseline wins the tie and the margin
        keeps using the *old* rate (e.g. 205 − 150 instead of 205 − 165). The
        enumerate index is a robust tiebreak both before flush (in-memory append
        order) and after (the schedule loads ``effective_from, id`` → newer step
        last). Falls back to the legacy column when the schedule is empty
        (contracts that predate the schedule).
        """
        entries = list(schedule or [])
        if not entries:
            return fallback
        past = [(i, e) for i, e in enumerate(entries) if e.effective_from <= on]
        if past:
            _, step = max(past, key=lambda ie: (ie[1].effective_from, ie[0]))
            return step.rate
        # Only future-dated steps: earliest upcoming, last-inserted breaks ties.
        earliest = min(e.effective_from for e in entries)
        _, step = max(
            (ie for ie in enumerate(entries) if ie[1].effective_from == earliest),
            key=lambda ie: ie[0],
        )
        return step.rate

    def effective_candidate_rate(self, on: date) -> Optional[int]:
        """Candidate rate in effect on ``on`` — see ``_resolve_scheduled_rate``.

        Falls back to the legacy ``rate_candidate`` column when no schedule
        exists. Requires ``candidate_rate_schedule`` to be eager-loaded — callers
        serialize within async sessions.
        """
        return self._resolve_scheduled_rate(
            self.candidate_rate_schedule, on, self.rate_candidate
        )

    def effective_client_rate(self, on: date) -> Optional[Decimal]:
        """Client rate in effect on ``on`` — see ``_resolve_scheduled_rate``.

        Mirror of ``effective_candidate_rate`` for the client-rate schedule.
        Falls back to the legacy ``rate_client`` column when no schedule exists
        (contracts without a client-rate amendment, the common case). Requires
        ``client_rate_schedule`` to be eager-loaded.
        """
        return self._resolve_scheduled_rate(
            self.client_rate_schedule, on, self.rate_client
        )

    def effective_framework_rate(self, on: date) -> Optional[Decimal]:
        """Framework rate in effect on ``on`` — see ``_resolve_scheduled_rate``.

        Mirror of ``effective_client_rate`` for the framework-rate schedule.
        Falls back to the legacy ``framework_rate`` column when no schedule exists
        (the common case). Informational only — never feeds the margin. Requires
        ``framework_rate_schedule`` to be eager-loaded.
        """
        return self._resolve_scheduled_rate(
            self.framework_rate_schedule, on, self.framework_rate
        )

    def monthly_rate(self, rate: object) -> Optional[Decimal]:
        """Normalize a stored rate to a monthly amount using rate_unit + billing_hours."""
        dec = self._as_decimal(rate)
        if dec is None:
            return None
        if self.rate_unit == RateUnit.monthly:
            return dec
        if self.rate_unit == RateUnit.daily:
            return dec * 22  # standardowy miesiąc roboczy (PL)
        if self.rate_unit == RateUnit.hourly:
            return dec * (self.billing_hours_per_month or 160)
        return dec

    @property
    def monthly_rate_client(self) -> Optional[Decimal]:
        return self.monthly_rate(self.rate_client)

    @property
    def monthly_rate_candidate(self) -> Optional[Decimal]:
        return self.monthly_rate(self.rate_candidate)

    @property
    def monthly_margin(self) -> Optional[Decimal]:
        c, k = self.monthly_rate_client, self.monthly_rate_candidate
        if c is None or k is None:
            return None
        return c - k

    @property
    def hours_pool_remaining(self) -> Optional[int]:
        """Pozostałe godziny w puli (total - consumed). None gdy nie godzinowy."""
        if self.hours_pool_total is None:
            return None
        return self.hours_pool_total - (self.hours_pool_consumed or 0)

    @property
    def hours_pool_usage_pct(self) -> Optional[float]:
        """Procent zużycia puli godzin (0–100+). None gdy brak/zerowa pula."""
        if not self.hours_pool_total:
            return None
        return round((self.hours_pool_consumed or 0) / self.hours_pool_total * 100, 1)

    def __repr__(self) -> str:
        return f"<Contract id={self.id} candidate={self.candidate_id} client={self.client_id} status={self.status}>"


@event.listens_for(Contract, "before_insert")
@event.listens_for(Contract, "before_update")
def auto_calculate_margin(mapper, connection, target: Contract):
    """Automatically recalculate margin before save."""
    target.margin = target.calculate_margin()
