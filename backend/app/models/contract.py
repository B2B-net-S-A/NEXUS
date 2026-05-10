import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, event
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
    active = "active"
    ending = "ending"  # < 30 dni do końca
    ended = "ended"


class RateUnit(str, enum.Enum):
    hourly = "hourly"
    daily = "daily"
    monthly = "monthly"


class ContractWorkMode(str, enum.Enum):
    remote = "remote"
    hybrid = "hybrid"
    onsite = "onsite"


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
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id"), nullable=False, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"), index=True)

    # Daty
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date)

    # Stawki finansowe
    rate_candidate: Mapped[Optional[int]] = mapped_column(Integer)
    rate_client: Mapped[Optional[int]] = mapped_column(Integer)
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

    # Marża — obliczana automatycznie (rate_client - rate_candidate)
    margin: Mapped[Optional[int]] = mapped_column(Integer)

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
    work_mode: Mapped[Optional[ContractWorkMode]] = mapped_column(
        Enum(ContractWorkMode, name="contractworkmode"), nullable=True
    )
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

    # Desired rate range we want to achieve on this contract (used by benchmark
    # comparison and by sales during renegotiation).
    target_rate_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_rate_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # End of the client's purchase order — often earlier than our contract with
    # the consultant. Drives proactive reminders so we can react before the
    # order lapses.
    client_order_end_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
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

    def calculate_margin(self) -> Optional[int]:
        """Oblicz marżę: stawka klienta - stawka kandydata (w tej samej jednostce)."""
        if self.rate_client is not None and self.rate_candidate is not None:
            return self.rate_client - self.rate_candidate
        return None

    def monthly_rate(self, rate: Optional[int]) -> Optional[int]:
        """Normalize a stored rate to a monthly amount using rate_unit + billing_hours."""
        if rate is None:
            return None
        if self.rate_unit == RateUnit.monthly:
            return rate
        if self.rate_unit == RateUnit.daily:
            return rate * 22  # standardowy miesiąc roboczy (PL)
        if self.rate_unit == RateUnit.hourly:
            return rate * (self.billing_hours_per_month or 160)
        return rate

    @property
    def monthly_rate_client(self) -> Optional[int]:
        return self.monthly_rate(self.rate_client)

    @property
    def monthly_rate_candidate(self) -> Optional[int]:
        return self.monthly_rate(self.rate_candidate)

    @property
    def monthly_margin(self) -> Optional[int]:
        c, k = self.monthly_rate_client, self.monthly_rate_candidate
        if c is None or k is None:
            return None
        return c - k

    def __repr__(self) -> str:
        return f"<Contract id={self.id} candidate={self.candidate_id} client={self.client_id} status={self.status}>"


@event.listens_for(Contract, "before_insert")
@event.listens_for(Contract, "before_update")
def auto_calculate_margin(mapper, connection, target: Contract):
    """Automatically recalculate margin before save."""
    target.margin = target.calculate_margin()
