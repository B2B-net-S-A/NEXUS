import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.linkedin_snapshot import LinkedinSyncStatus


class CandidateStatus(str, enum.Enum):
    active = "active"
    passive = "passive"
    blacklisted = "blacklisted"


class AvailabilityStatus(str, enum.Enum):
    """
    Postawa konsultanta wobec sourcingu (ortogonalna do `status` i stanu
    zatrudnienia). `status` mówi czym jest kandydat w bazie, a
    `availability_status` czy interesują go nowe projekty.
    """

    actively_looking = "actively_looking"  # Aktywnie szuka pracy
    open_to_offers = "open_to_offers"  # Otwarty na dodatkowe projekty
    not_looking = "not_looking"  # Nie szuka — spokojnie siedzi
    unknown = "unknown"  # Default — nie wiemy


class CandidateSource(str, enum.Enum):
    linkedin = "linkedin"
    pracuj = "pracuj"
    jjit = "jjit"
    referral = "referral"
    database = "database"
    manual = "manual"


class Candidate(Base, TimestampMixin):
    """
    Kandydat/profil zawodowy.
    Przechowuje dane kontaktowe, kompetencje, CV i wektor embeddingu.
    """

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Dane osobowe
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    lastname: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    location: Mapped[Optional[str]] = mapped_column(String(255))
    linkedin: Mapped[Optional[str]] = mapped_column(String(500))

    # Avatar
    avatar_url: Mapped[Optional[str]] = mapped_column(String(1000))

    # Oczekiwania finansowe (PLN/mies.)
    salary_expectation: Mapped[Optional[int]] = mapped_column(Integer)
    salary_currency: Mapped[Optional[str]] = mapped_column(String(3), default="PLN")
    availability_date: Mapped[Optional[date]] = mapped_column(Date)
    notice_period: Mapped[Optional[int]] = mapped_column(Integer)  # days

    # Źródło pozyskania kandydata
    source: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    source_enum: Mapped[Optional[CandidateSource]] = mapped_column(
        Enum(CandidateSource, name="candidatesource"), nullable=True
    )

    # Competence category — legacy string field (Frontend/Backend/DevOps/QA/...).
    # Being replaced by `competence_category_id` FK (below). Kept for backfill
    # safety; drop in a follow-up migration after audit.
    competence_category: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    competence_category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("competence_categories.id"), nullable=True, index=True
    )

    # Structured IT experience in years (dedicated column; supplements `experience` JSONB)
    years_it_experience: Mapped[Optional[int]] = mapped_column(Integer)

    # AI Summary
    ai_summary: Mapped[Optional[str]] = mapped_column(Text)

    # Candidate preferences (matching-engine input)
    # Shape:
    #   {
    #     "remote_modes": ["remote", "hybrid", "onsite"],
    #     "rate_min": int, "rate_max": int, "rate_currency": str,
    #     "industries": ["fintech", "banking", ...],
    #     "excluded_clients": [client_id, ...],
    #     "contract_types": ["b2b", "uop", "zlecenie"],
    #   }
    preferences: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # "Champion" flag — top performer (verified high quality)
    champion: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # ── Engagement flags (Phase: Kontrakty expansion) ────────────────────
    # Boolean cues used by TAC/delivery to match a consultant to extra value
    # beyond their current engagement: referrals, screening help, expert
    # consultations, sales support, etc. Stored on candidate (cecha stała,
    # przenosi się między kontraktami).
    is_ambassador: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    wants_to_verify_candidates: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    open_to_side_projects: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    open_to_sales_support: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    open_to_expert_consult: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    # TTL/freshness per flag — NULL = nigdy nie zadeklarowano/potwierdzono.
    # Auto-updated przez PATCH /engagement gdy flaga jest dotknięta — także
    # gdy wartość się nie zmienia (rekruter „potwierdza" świeżość przez nudge).
    open_to_side_projects_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    open_to_sales_support_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    open_to_expert_consult_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    engagement_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Structured location (Phase: Kontrakty expansion) ─────────────────
    # Legacy free-text `location` above is kept for compatibility; these
    # fields enable heat-maps, regional meetups, hub-based project teams.
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    hub_city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Numeric(9, 6), nullable=True)

    # ── Business entity / JDG (migracja 0058) ────────────────────────────
    # Dane do generowania umów B2B i wystawiania faktur. `business_form`
    # rozróżnia jdg / sp_zoo / sa / sc / osoba_fizyczna — sterownik dla
    # warunków w szablonach Jinja umów.
    legal_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    nip: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    regon: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    business_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    business_form: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Who verified / last screened this candidate
    verifier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    # Who added this candidate (recruiter ownership).
    # Nullable because imported rows (Traffit, talent-radar, CSV) pre-date the
    # column — the list filter exposes a `0` sentinel that maps these to
    # "System import".
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # List of technologies verified during screening — structured tag list
    # Shape: [{"name": str, "level": "expert|senior|mid|junior", "years": int}, ...]
    verified_tech: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)

    # Status kandydata w bazie
    status: Mapped[CandidateStatus] = mapped_column(
        Enum(CandidateStatus),
        default=CandidateStatus.active,
        nullable=False,
        index=True,
    )

    # Postawa wobec sourcingu — niezależna od statusu w bazie (Phase: Wyróżnienia).
    availability_status: Mapped[AvailabilityStatus] = mapped_column(
        Enum(AvailabilityStatus, name="availabilitystatus"),
        default=AvailabilityStatus.unknown,
        server_default="unknown",
        nullable=False,
        index=True,
    )

    # Dane strukturalne JSONB
    tags: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=list
    )  # np. ["senior", "python"]
    skills: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=list
    )  # [{name, level, years}]
    experience: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=list
    )  # [{company, role, start, end, desc}]
    education: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=list
    )  # [{school, degree, field, year}]
    languages: Mapped[Optional[dict]] = mapped_column(
        JSONB, default=list
    )  # [{lang, level}]

    # CV
    raw_cv_text: Mapped[Optional[str]] = mapped_column(Text)
    cv_filename: Mapped[Optional[str]] = mapped_column(String(500))
    cv_parsed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ── LinkedIn employment tracking (Phase: LinkedIn sync) ──────────────
    # Denormalized fast-path fields mirror the latest snapshot (stored in
    # `candidate_linkedin_snapshots`). `linkedin_employment_changed_at` is set
    # ONLY when the sync detects a new employer — drives the "recently changed
    # jobs" filter and the candidate-card badge. Title-only changes (awans) are
    # recorded in the snapshot but do not pollute this timestamp.
    linkedin_current_company: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    linkedin_current_title: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    linkedin_current_started_at: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True
    )
    linkedin_employment_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    linkedin_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    linkedin_sync_status: Mapped[LinkedinSyncStatus] = mapped_column(
        Enum(LinkedinSyncStatus, name="linkedinsyncstatus"),
        default=LinkedinSyncStatus.disabled,
        server_default="disabled",
        nullable=False,
    )
    linkedin_sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Sprint 7a — external sources (Traffit / talent-radar / CSV imports)
    external_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )
    cv_file_content: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    # Klucz w Hetzner Object Storage (audit-2026-05-07 round 2, migracja 0080).
    # Po finalize-delete-bytea cv_file_content = NULL dla zmigrowanych rekordów.
    cv_storage_key: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, index=True
    )
    cv_language: Mapped[Optional[str]] = mapped_column(String(10))
    cv_extracted_data: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    # Metadane rekrutacyjne
    notes_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_contacted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # Powiązanie z wektorem w Qdrant
    embedding_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)

    # Relationships
    notes = relationship(
        "Note", back_populates="candidate", cascade="all, delete-orphan"
    )
    documents = relationship(
        "CandidateDocument", back_populates="candidate", cascade="all, delete-orphan"
    )
    chat_messages = relationship(
        "CandidateChatMessage",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )
    pipeline_stages = relationship(
        "CandidateStage", back_populates="candidate", cascade="all, delete-orphan"
    )
    risk_profile = relationship(
        "CandidateRiskProfile",
        back_populates="candidate",
        uselist=False,
        cascade="all, delete-orphan",
    )
    contracts = relationship("Contract", back_populates="candidate")
    calls = relationship(
        "Call", back_populates="candidate", cascade="all, delete-orphan"
    )
    rate_history = relationship(
        "RateHistory", back_populates="candidate", cascade="all, delete-orphan"
    )
    conflicts = relationship(
        "CandidateConflict", back_populates="candidate", cascade="all, delete-orphan"
    )
    verifier = relationship("User", foreign_keys=[verifier_id])
    creator = relationship("User", foreign_keys=[created_by])
    competence_category_ref = relationship(
        "CompetenceCategory", foreign_keys=[competence_category_id]
    )
    # Multi-CC assignment (migracja 0041_ai_cc_matching). Kandydat może mieć
    # 1 primary + 2 secondary CC, z różnym source (ai_auto/ai_suggested/manual).
    competence_categories = relationship(
        "CandidateCompetenceCategory",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )
    linkedin_snapshots = relationship(
        "CandidateLinkedinSnapshot",
        back_populates="candidate",
        cascade="all, delete-orphan",
        order_by="desc(CandidateLinkedinSnapshot.fetched_at)",
    )

    def __repr__(self) -> str:
        return f"<Candidate id={self.id} name={self.name} {self.lastname}>"
