"""Dane Generatora Umów B2B per-umowa (1:1 z `Contract`).

Izoluje pola specyficzne dla generatora od modelu `Contract` (brak bloatu hot
tabeli). `role_scope_override` (lista bulletów) pozwala nadpisać domyślny zakres
roli na poziomie konkretnej umowy; `NULL` = użyj zakresu z `B2BContractRole`.
"""

from datetime import date
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class B2BContractDetail(Base, TimestampMixin):
    __tablename__ = "b2b_contract_details"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Pola edytowalne wypełniane w generatorze (część = pre-fill z kandydata/
    # rekrutacji, część wpisywana ręcznie).
    contract_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    signing_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    project_city: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    project_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correspondence_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rate_in_words: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Język wygenerowanego dokumentu: 'pl' | 'en'.
    language: Mapped[str] = mapped_column(
        String(2), default="pl", server_default="pl", nullable=False
    )

    b2b_role_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("b2b_contract_roles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Per-umowa override zakresu (lista bulletów); NULL = domyślny z roli.
    role_scope_override: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    contract = relationship("Contract", back_populates="b2b_detail")
    role = relationship("B2BContractRole")

    def __repr__(self) -> str:
        return f"<B2BContractDetail id={self.id} contract={self.contract_id}>"
