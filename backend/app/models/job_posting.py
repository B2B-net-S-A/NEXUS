import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class Portal(str, enum.Enum):
    pracuj_pl = "pracuj_pl"
    justjoinit = "justjoinit"
    linkedin = "linkedin"
    nofluffjobs = "nofluffjobs"
    bulldogjob = "bulldogjob"


class PostingStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    expired = "expired"
    removed = "removed"


class JobPosting(Base, TimestampMixin):
    """
    Publikacja oferty pracy na zewnętrznym portalu ogłoszeniowym.
    Integracja z portalami w przygotowaniu — dane symulowane.
    """
    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    portal: Mapped[Portal] = mapped_column(Enum(Portal), nullable=False)

    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[PostingStatus] = mapped_column(
        Enum(PostingStatus), default=PostingStatus.draft, nullable=False, index=True
    )

    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applications: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    job = relationship("Job", back_populates="postings")

    def __repr__(self) -> str:
        return f"<JobPosting id={self.id} job_id={self.job_id} portal={self.portal} status={self.status}>"
