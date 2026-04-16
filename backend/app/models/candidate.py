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
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class CandidateStatus(str, enum.Enum):
    active = "active"
    passive = "passive"
    blacklisted = "blacklisted"


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

    # Competence category (e.g. Frontend, Backend, DevOps, QA)
    competence_category: Mapped[Optional[str]] = mapped_column(String(100), index=True)

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

    # Who verified / last screened this candidate
    verifier_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
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

    # Sprint 7a — external sources (Traffit / talent-radar / CSV imports)
    external_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )
    cv_file_content: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
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
    pipeline_stages = relationship(
        "CandidateStage", back_populates="candidate", cascade="all, delete-orphan"
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

    def __repr__(self) -> str:
        return f"<Candidate id={self.id} name={self.name} {self.lastname}>"
