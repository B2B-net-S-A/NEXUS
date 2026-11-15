"""Wniosek o dopłatę za technologię premium dla kontraktu (0711, F3).

Historia osoby: zamknięte wnioski zostają (przyznana z potwierdzeniem klienta,
odmowa z powodem i datą kolejnej próby). Logika w ``services/premium_skills.py``.
"""

from datetime import date
from typing import Optional

from sqlalchemy import Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class ContractPremiumSkillClaim(Base, TimestampMixin):
    __tablename__ = "contract_premium_skill_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    technology: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="approved")
    knows: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    uses: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    evidence: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    dl_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    dl_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    client_confirmed_by: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    client_confirmed_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    client_evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    outcome_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_try_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
