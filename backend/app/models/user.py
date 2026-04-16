import enum

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class UserRole(str, enum.Enum):
    """
    Jedna, skonsolidowana hierarchia ról dla procesu B2B.net:

    - admin         — zarządzanie systemem i userami
    - delivery_lead — kierownik procesu, rate cards, konflikty, pipeline templates
    - tac           — Talent Acquisition Consultant (hybryda ATS + LinkedIn)
    - recruiter     — 100% LinkedIn, dodaje kandydatów
    - sourcer       — 100% ATS + ogłoszenia
    - user          — read-only viewer (także Quality Control / klient)
    """

    admin = "admin"
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
