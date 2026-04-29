"""LinkedIn daily metrics — manual entry per user per dzień.

Trackowane:
  - cv_added: nowe CV kandydatów zaimportowane z LinkedIn
  - messages_sent: wysłane wiadomości LinkedIn (InMail / direct)
  - responses_received: otrzymane odpowiedzi
  - notes: freeform

Agregaty (week/month) liczone w serwisie; widok surowy — tabela bulk-edit
dla adminów.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class LinkedInDailyMetric(Base):
    """Jeden wiersz = jeden user × jeden dzień."""

    __tablename__ = "linkedin_daily_metrics"
    __table_args__ = (
        UniqueConstraint("user_id", "report_date", name="uq_linkedin_daily"),
        CheckConstraint(
            "cv_added >= 0 AND messages_sent >= 0 AND responses_received >= 0",
            name="ck_linkedin_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    week_number: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    cv_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    messages_sent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    responses_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", foreign_keys=[user_id])
    creator = relationship("User", foreign_keys=[created_by])

    def __repr__(self) -> str:
        return (
            f"<LinkedInDailyMetric user={self.user_id} "
            f"date={self.report_date} cv={self.cv_added}>"
        )
