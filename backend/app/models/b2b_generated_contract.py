"""Log wygenerowanych umów B2B — numeracja + audyt.

Standalone render (bez rekordu `Contract`) zapisuje tu wiersz przy pobraniu
finalnego DOCX. Numer umowy = kolejny w obrębie roku (`max(seq)+1`), więc
auto-numeracja uwzględnia wcześniej wygenerowane umowy (także ręczne/standalone).
"""

from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class B2BGeneratedContract(Base, TimestampMixin):
    __tablename__ = "b2b_generated_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    contract_number: Mapped[str] = mapped_column(String(64), nullable=False)
    partner_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    language: Mapped[str] = mapped_column(String(2), default="pl", nullable=False)
    signing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return f"<B2BGeneratedContract id={self.id} number={self.contract_number!r}>"
