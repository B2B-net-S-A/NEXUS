import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text
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

    remote_policy: Mapped[RemotePolicy] = mapped_column(
        Enum(RemotePolicy), default=RemotePolicy.hybrid, nullable=False
    )

    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus), default=JobStatus.draft, nullable=False, index=True
    )

    priority: Mapped[JobPriority] = mapped_column(
        Enum(JobPriority), default=JobPriority.medium, nullable=False
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

    # Foreign keys
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id"), index=True
    )
    recruiter_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    pipeline_template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pipeline_templates.id"), nullable=True, index=True
    )

    # Relationships
    client = relationship("Client", back_populates="jobs")
    recruiter = relationship("User", foreign_keys=[recruiter_id])
    creator = relationship("User", foreign_keys=[created_by])
    pipeline_template = relationship("PipelineTemplate")
    pipeline_stages = relationship(
        "CandidateStage", back_populates="job", cascade="all, delete-orphan"
    )
    notes = relationship("Note", back_populates="job")
    contracts = relationship("Contract", back_populates="job")
    postings = relationship(
        "JobPosting", back_populates="job", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Job id={self.id} title={self.title} status={self.status}>"
