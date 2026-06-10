"""Log wygenerowanych umów B2B — numeracja + audyt.

Standalone render (bez rekordu `Contract`) zapisuje tu wiersz przy pobraniu
finalnego DOCX. `contract_number` jest zawsze kanoniczny („1434/2026”), a `seq`
to jego liczbowy prefiks — stąd UNIQUE(year, seq) gwarantuje na poziomie DB,
że numer umowy nie powtórzy się w obrębie roku (race-safe, w odróżnieniu od
samego SELECT-checku w API).

Legacy (wiersze sprzed PR #469, id 5-7 na prod): `seq` był licznikiem wierszy
niezależnym od numeru — dlatego constraint NIE jest na (year, contract_number)
(prod ma historyczny duplikat „1434/2026”, którego nie ruszamy bez decyzji).
"""

from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class B2BGeneratedContract(Base, TimestampMixin):
    __tablename__ = "b2b_generated_contracts"
    __table_args__ = (
        Index("uq_b2b_generated_contracts_year_seq", "year", "seq", unique=True),
    )

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
