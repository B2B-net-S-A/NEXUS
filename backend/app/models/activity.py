from typing import Optional

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class Activity(Base, TimestampMixin):
    """
    Dziennik aktywności — audit trail wszystkich zmian w systemie.
    Każda operacja CRUD na encjach jest tu rejestrowana.
    """

    __tablename__ = "activities"
    __table_args__ = (
        Index(
            "ix_activities_candidate_manual_edit",
            "entity_type",
            "entity_id",
            "action",
            "external_source",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Typ encji: "candidate", "job", "client", "contract", "note", "pipeline"
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Akcja: "created", "updated", "deleted", "stage_changed", "cv_uploaded", ...
    action: Mapped[str] = mapped_column(String(100), nullable=False)

    # Szczegóły w JSON — przed/po zmianie, dodatkowe dane
    details: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)

    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), index=True)

    # External source tracking — Traffit activity_id itp.
    # Migracja 0075 dodaje partial unique index na (external_source, external_id).
    external_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )

    # Relationships
    user = relationship("User", back_populates="activities")

    def __repr__(self) -> str:
        return f"<Activity id={self.id} entity={self.entity_type}:{self.entity_id} action={self.action}>"
