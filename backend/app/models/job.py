import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class RemotePolicy(str, enum.Enum):
    onsite = "onsite"
    hybrid = "hybrid"
    remote = "remote"


class JobStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    closed = "closed"


class JobPriority(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    urgent = "urgent"


class RecruitmentType(str, enum.Enum):
    body_leasing = "body_leasing"
    sales_project = "sales_project"
    tender = "tender"


class Seniority(str, enum.Enum):
    junior = "junior"
    mid = "mid"
    senior = "senior"
    lead = "lead"
    architect = "architect"


class WorkMode(str, enum.Enum):
    fulltime = "fulltime"
    parttime = "parttime"
    contract = "contract"


class JobCloseReason(str, enum.Enum):
    """Powód zamknięcia oferty bez placementu (dla sekcji 'Przegrane rekrutacje')."""

    budget = "budget"
    internal_hire = "internal_hire"
    competitor = "competitor"
    paused = "paused"
    filled_by_us = "filled_by_us"
    client_ghosted = "client_ghosted"
    other = "other"


class Job(Base, TimestampMixin):
    """
    Oferta pracy / zlecenie rekrutacyjne.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    requirements: Mapped[Optional[str]] = mapped_column(Text)
    location: Mapped[Optional[str]] = mapped_column(String(255))

    # Wynagrodzenie (B2B, PLN/mies.)
    salary_min: Mapped[Optional[int]] = mapped_column(Integer)
    salary_max: Mapped[Optional[int]] = mapped_column(Integer)
    # Budżet PLN/h DLA KANDYDATA (dealbreaker-switch, 0235). Jedyna jednostka
    # porównywalna z candidate.expected_rate_hourly — salary_min/max wyżej to
    # legacy PLN/mies. bez polityki konwersji. Fallback: stawka Championa.
    rate_budget_hourly: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2))

    remote_policy: Mapped[RemotePolicy] = mapped_column(
        Enum(RemotePolicy), default=RemotePolicy.hybrid, nullable=False
    )

    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.draft, nullable=False, index=True
    )

    priority: Mapped[JobPriority] = mapped_column(
        Enum(JobPriority), default=JobPriority.medium, nullable=False
    )

    # Flagged by Delivery Lead (during onboarding or from the jobs list) to
    # signal the role needs active candidate sourcing.
    needs_sourcing: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    recruitment_type: Mapped[RecruitmentType] = mapped_column(
        Enum(RecruitmentType),
        default=RecruitmentType.body_leasing,
        nullable=False,
        index=True,
    )

    deadline: Mapped[Optional[date]] = mapped_column(Date)

    # Portale ogłoszeniowe — lista opublikowanych URL/statusów
    portals: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Structured matching-criteria (must-have vs nice-to-have)
    # Shape: [{"name": str, "level": "expert|senior|mid|junior", "years": int, "category": str}, ...]
    must_skills: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)
    nice_skills: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)

    # Additional job metadata
    seniority: Mapped[Optional[Seniority]] = mapped_column(
        Enum(Seniority, name="seniority"), nullable=True
    )
    work_mode: Mapped[WorkMode] = mapped_column(
        Enum(WorkMode, name="workmode"), default=WorkMode.fulltime, nullable=False
    )
    headcount: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    reference_number: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, unique=True
    )
    industry: Mapped[Optional[str]] = mapped_column(
        String(50), nullable=True, index=True
    )
    subcategory: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Phase 15 (migration 0055): Programme / Agile Release Train identifier.
    # Free-text (np. "ART Payments", "CIB Mortgages", "TRAIN-X") used by the
    # historical-jobs suggestion source as a same-train boost when retrieving
    # similar closed roles for Champion Profile pre-fill.
    train_name: Mapped[Optional[str]] = mapped_column(
        String(128), nullable=True, index=True
    )

    # Freeform custom fields — Faza 4 will replace with dedicated engine
    custom_fields: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Phase 10: "Profil Championa" — Delivery Lead fills this once per job.
    # Shape validated by app.schemas.champion.ChampionProfile.
    champion_profile: Mapped[Optional[dict]] = mapped_column(
        JSONB, nullable=True, default=None
    )

    # Persisted Qdrant embedding reference (populated by Faza 2 scoring)
    embedding_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )
    criteria_generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Timestamp zamknięcia zapytania — ustawiany przy zmianie statusu na `closed`.
    # Używany przez /api/reports/clients (hit ratio per client) do filtra okresu.
    # Historycznie backfillowany z `updated_at` w migracji 0047_job_closed_at.
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Close reason metadata (migracja 0048_job_close_reason). Populated by
    # POST /jobs/{id}/close when status flips to `closed`. NULL for legacy
    # closed rows — UI shows "Nie określono" as fallback.
    close_reason: Mapped[Optional[JobCloseReason]] = mapped_column(
        Enum(JobCloseReason, name="jobclosereason"), nullable=True
    )
    close_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Foreign keys
    # client_id: enforced NOT NULL od migracji 0120 (2026-05-27). Wcześniej
    # nullable — QA sweep wykrył 21 orphan recordów (test/junk data) na prod.
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id"), index=True, nullable=False
    )
    # Primary Competence Category (migracja 0033_cc_entities + 0041_ai_cc_matching).
    # Kolumna istnieje w DB od 0033, ale dopiero 0041 domyka mapping w ORM —
    # wcześniej dostęp był tylko przez raw SQL / osobne entity queries.
    competence_category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("competence_categories.id"), nullable=True, index=True
    )
    recruiter_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    # Delivery Lead odpowiedzialny za realizację requesta (body leasing).
    # NULL dla sales_project/tender lub gdy nieprzypisany. Fallback przy
    # raportowaniu: `delivery_lead_client_assignments.is_head=true` dla
    # client_id.
    delivery_lead_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    # TAC (Talent Acquisition Consultant) — osoba opiekująca się relacją z
    # klientem. Przy POST /jobs auto-ustawiany tylko gdy klient ma dokładnie
    # jedno aktywne przypisanie TAC. Przy wielu równych TAC-ach caller musi
    # podać jawny `tac_id`, należący do zespołu tego klienta.
    tac_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    # Hiring manager po stronie klienta (Contact w firmie klienta — osoba
    # która zatrudnia). Migracja 0097. Nullable bo backfill manual; analytics
    # może filtrować/agregować po tej osobie. ON DELETE SET NULL — kasacja
    # Contact nie kasuje Job, tylko zeruje link.
    hiring_manager_contact_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    pipeline_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pipeline_templates.id"), nullable=True, index=True
    )

    # External source tracking — Traffit / future imports.
    # Migracja 0074 dodaje partial unique index na (external_source, external_id).
    external_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )

    @property
    def managed_by(self) -> Optional[str]:
        """Właściciel procesu podczas koegzystencji z Traffit (API contract)."""
        return "traffit" if self.external_source == "traffit" else None

    @property
    def integration(self) -> Optional[dict]:
        if self.external_source != "traffit":
            return None
        return {
            "system": "traffit",
            "state": "synced",
            "external_id": self.external_id,
            "last_synced_at": self.updated_at,
        }

    # Relationships
    client = relationship("Client", back_populates="jobs")
    competence_category = relationship(
        "CompetenceCategory", foreign_keys=[competence_category_id]
    )
    secondary_cc_links = relationship(
        "JobSecondaryCc",
        foreign_keys="JobSecondaryCc.job_id",
        cascade="all, delete-orphan",
    )
    recruiter = relationship("User", foreign_keys=[recruiter_id])
    delivery_lead = relationship("User", foreign_keys=[delivery_lead_id])
    tac = relationship("User", foreign_keys=[tac_id])
    creator = relationship("User", foreign_keys=[created_by])
    pipeline_template = relationship("PipelineTemplate")
    pipeline_stages = relationship(
        "CandidateStage", back_populates="job", cascade="all, delete-orphan"
    )
    notes = relationship("Note", back_populates="job")
    chat_messages = relationship(
        "JobChatMessage", back_populates="job", cascade="all, delete-orphan"
    )
    contracts = relationship("Contract", back_populates="job")
    postings = relationship(
        "JobPosting", back_populates="job", cascade="all, delete-orphan"
    )
    question_links = relationship(
        "JobQuestion", back_populates="job", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Job id={self.id} title={self.title} status={self.status}>"
