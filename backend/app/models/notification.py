import enum
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class NotificationType(str, enum.Enum):
    contract_ending = "contract_ending"
    interview_scheduled = "interview_scheduled"
    candidate_added = "candidate_added"
    stage_changed = "stage_changed"
    new_application = "new_application"


class Notification(Base, TimestampMixin):
    """
    Powiadomienie systemowe dla użytkownika.
    """
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # URL to navigate to when clicked
    link: Mapped[Optional[str]] = mapped_column(String(1000))

    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notificationtype"),
        nullable=False,
        index=True,
    )

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<Notification id={self.id} user={self.user_id} type={self.notification_type} read={self.is_read}>"
