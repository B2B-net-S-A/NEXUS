import enum
from typing import Optional

from sqlalchemy import Boolean, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class UserRole(str, enum.Enum):
    admin = "admin"
    recruiter = "recruiter"
    manager = "manager"
    client = "client"


class RecruiterRole(str, enum.Enum):
    """Operational recruitment role — separate from auth role."""

    recruiter = "recruiter"
    sourcer = "sourcer"
    tac = "tac"
    delivery_lead = "delivery_lead"
    quality_control = "quality_control"
    admin = "admin"


class User(Base, TimestampMixin):
    """
    Użytkownik systemu (Admin, Rekruter, Manager, Klient).
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole), default=UserRole.recruiter, nullable=False
    )
    recruiter_role: Mapped[Optional[RecruiterRole]] = mapped_column(
        Enum(RecruiterRole, name="recruiterrole"), nullable=True
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
