import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
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
    # 0358: zgłoszone do publikacji, czeka na worker portali.
    publishing = "publishing"
    published = "published"
    expired = "expired"
    removed = "removed"
    # 0358: portal odmówił albo nie jest skonfigurowany (`last_error`).
    failed = "failed"


class JobPosting(Base, TimestampMixin):
    """Publikacja rekrutacji na zewnętrznym portalu ogłoszeniowym (0358).

    Wiersz jest też pozycją kolejki: ``publishing`` czeka na worker
    ``tasks/job_portal_worker``, który woła adapter portalu
    (``services/job_portals``). Treść idzie WYŁĄCZNIE z zatwierdzonego opisu
    publicznego — ``public_profile_hash`` mówi, z której wersji. Najwyżej
    jedna żywa (``publishing``/``published``) publikacja rekrutacji na portal
    (``uq_job_postings_live_per_portal``). Do 0358 zakładka „Portale”
    zapisywała tu symulowane wiersze ``SIM-…`` — usunięte migracją.
    """

    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    portal: Mapped[Portal] = mapped_column(Enum(Portal), nullable=False)

    external_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    status: Mapped[PostingStatus] = mapped_column(
        Enum(PostingStatus), default=PostingStatus.draft, nullable=False, index=True
    )

    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)

    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    applications: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # 0358 — kolejka publikacji.
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    payload_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    public_profile_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    job = relationship("Job", back_populates="postings")

    def __repr__(self) -> str:
        return f"<JobPosting id={self.id} job_id={self.job_id} portal={self.portal} status={self.status}>"
