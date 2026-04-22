import enum
from typing import Optional

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class NotificationType(str, enum.Enum):
    contract_ending = "contract_ending"
    interview_scheduled = "interview_scheduled"
    candidate_added = "candidate_added"
    stage_changed = "stage_changed"
    new_application = "new_application"
    # Phase 13 — automated trigger alerts
    dl_stage_stale_6h = "dl_stage_stale_6h"
    client_feedback_eobd = "client_feedback_eobd"
    powercalling_kpi = "powercalling_kpi"
    candidate_feedback_1h = "candidate_feedback_1h"
    stage_stuck_7d = "stage_stuck_7d"
    # Phase 11 — realtime Champion Profile edits
    champion_profile_updated = "champion_profile_updated"
    # Kontrakty expansion — proactive contract/equipment/order reminders
    contract_ending_90d = "contract_ending_90d"
    equipment_return_due_14d = "equipment_return_due_14d"
    client_order_ending_30d = "client_order_ending_30d"


class Notification(Base, TimestampMixin):
    """
    Powiadomienie systemowe dla użytkownika.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # URL to navigate to when clicked
    link: Mapped[Optional[str]] = mapped_column(String(1000))

    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notificationtype"),
        nullable=False,
        index=True,
    )

    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, index=True
    )

    # Phase 13 — polymorphic dedup key. Pair (type, related_entity_id) + lokalny
    # dzień Warsaw tworzy unique index `ix_notif_dedup_daily`. Nie dodajemy FK
    # bo entity może być candidate_stage, call, candidate albo job.
    related_entity_type: Mapped[Optional[str]] = mapped_column(String(50))
    related_entity_id: Mapped[Optional[int]] = mapped_column(Integer, index=True)

    # Relationships
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return f"<Notification id={self.id} user={self.user_id} type={self.notification_type} read={self.is_read}>"
