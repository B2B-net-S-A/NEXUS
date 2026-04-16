from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TalentPool(Base):
    """Pula talentów — zbiór kandydatów według kategorii/technologii."""

    __tablename__ = "talent_pools"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    criteria: Mapped[Optional[dict]] = mapped_column(JSONB, default=dict)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    creator = relationship("User", foreign_keys=[created_by])
    memberships = relationship(
        "TalentPoolMembership", back_populates="pool", cascade="all, delete-orphan"
    )

    @property
    def candidate_count(self) -> int:
        return len(self.memberships)

    def __repr__(self) -> str:
        return f"<TalentPool id={self.id} name={self.name}>"


class TalentPoolMembership(Base):
    """Przynależność kandydata do puli talentów."""

    __tablename__ = "talent_pool_memberships"
    __table_args__ = (
        UniqueConstraint("talent_pool_id", "candidate_id", name="uq_pool_candidate"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    talent_pool_id: Mapped[int] = mapped_column(
        ForeignKey("talent_pools.id"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    added_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    pool = relationship("TalentPool", back_populates="memberships")
    candidate = relationship("Candidate", backref="pool_memberships")
    added_by_user = relationship("User", foreign_keys=[added_by])

    def __repr__(self) -> str:
        return f"<TalentPoolMembership pool={self.talent_pool_id} candidate={self.candidate_id}>"
