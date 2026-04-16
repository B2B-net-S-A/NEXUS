import enum
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class UserActionType(str, enum.Enum):
    candidate_added = "candidate_added"
    stage_changed = "stage_changed"
    call_made = "call_made"
    screening_done = "screening_done"
    interview_scheduled = "interview_scheduled"
    placement_closed = "placement_closed"
    note_added = "note_added"
    cv_uploaded = "cv_uploaded"


class UserActivity(Base):
    """
    Śledzenie aktywności użytkowników — każda czynność rekrutacyjna.
    Używane do dashboard performance i leaderboard.
    """

    __tablename__ = "user_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )

    # Typ akcji
    action_type: Mapped[UserActionType] = mapped_column(
        Enum(UserActionType, name="useractiontype"), nullable=False, index=True
    )

    # Kontekst encji (candidate, job, contract)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Szczegóły
    details: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    created_at: Mapped[object] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    # Relationships
    user = relationship("User", back_populates="user_activities")

    def __repr__(self) -> str:
        return (
            f"<UserActivity id={self.id} user={self.user_id} action={self.action_type}>"
        )
