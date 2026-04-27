import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class UserRole(str, enum.Enum):
    """
    Jedna, skonsolidowana hierarchia ról dla procesu B2B.net:

    - admin               — zarządzanie systemem i userami
    - head_of_recruitment — Olaf-type manager; odbiorca HR-owych agregatów
                            (PowerCalling, daily rollup) z notification_triggers
    - delivery_lead       — kierownik procesu, rate cards, konflikty,
                            pipeline templates
    - tac                 — Talent Acquisition Consultant (hybryda ATS + LinkedIn)
    - recruiter           — 100% LinkedIn, dodaje kandydatów
    - sourcer             — 100% ATS + ogłoszenia
    - user                — read-only viewer (także Quality Control / klient)

    Enum value `head_of_recruitment` is added at the DB level by migration
    `0029_notifications_triggers`; the Python enum must stay in sync.
    """

    admin = "admin"
    head_of_recruitment = "head_of_recruitment"
    delivery_lead = "delivery_lead"
    tac = "tac"
    recruiter = "recruiter"
    sourcer = "sourcer"
    user = "user"


class User(Base, TimestampMixin):
    """
    Użytkownik systemu. Jedna rola = jedno źródło prawdy.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="userrole"),
        default=UserRole.recruiter,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # KPI Coach opt-in flag. Default True → every operational recruiter gets
    # the in-app coaching (praise/remind/eod summary). User can disable in
    # Settings → Coaching. Non-operational roles (admin, head_of_recruitment,
    # delivery_lead, user) are filtered out at API/service layer regardless.
    kpi_coach_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )

    # First-login onboarding gate.
    # `delivery_lead` and `recruiter` must complete a role-specific onboarding
    # flow (see backend/app/api/onboarding.py) before accessing the app.
    # Existing users with other roles are backfilled to True by migration
    # 0035 so the rollout does not block them.
    profile_completed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    profile_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Last time this user had an active WS connection. Updated by
    # `ConnectionManager.connect/disconnect` in `app.api.ws`. Used by the
    # email-fallback background task: when a chat notification is older
    # than 15 min and the user's last_seen_at is also older than 15 min,
    # send the notification by email instead of just WS.
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # Relationships
    authored_notes = relationship(
        "Note", back_populates="author", foreign_keys="Note.author_id"
    )
    pipeline_moves = relationship(
        "CandidateStage",
        back_populates="moved_by_user",
        foreign_keys="CandidateStage.moved_by",
    )
    activities = relationship("Activity", back_populates="user")
    user_activities = relationship("UserActivity", back_populates="user")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"
