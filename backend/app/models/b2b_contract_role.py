"""Katalog ról B2B dla Generatora Umów — gotowe zakresy usług (PL/EN).

Każda rola należy do jednej z 5 kategorii kompetencji (`category_key` spójny
z Competence Categories) i niesie:
  - krótką etykietę „obszar usług" (do §1 umowy, np. „Software Development"),
  - pełny zakres obowiązków jako listę bulletów (do Załącznika nr 3).

Treści redagowane językiem rezultatu/usługi — **bez znamion umowy o pracę**
(art. 22 §1 KP): niezależność organizacyjna, własny warsztat i czas, własne
ryzyko gospodarcze, brak poleceń przełożonego / sztywnych godzin / urlopu.

Rekordy są edytowalne w UI; seed jest idempotentny (insert-if-missing), więc
nigdy nie nadpisuje ręcznych zmian.
"""

import enum

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class B2BRoleCategory(str, enum.Enum):
    """5 kategorii ról (spójne z Competence Categories)."""

    infra = "infra"  # Infrastruktura i Operacje
    dev = "dev"  # Rozwój Oprogramowania
    data_ai = "data_ai"  # Dane i AI
    security_qa = "security_qa"  # Bezpieczeństwo i Jakość
    management = "management"  # Zarządzanie i Dostarczanie


class B2BContractRole(Base, TimestampMixin):
    """Rola B2B z gotowym, dwujęzycznym zakresem usług."""

    __tablename__ = "b2b_contract_roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # category_key = wartość B2BRoleCategory (przechowywana jako string dla
    # elastyczności edycji w UI; bez twardego enuma na poziomie kolumny).
    category_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    category_label_pl: Mapped[str] = mapped_column(String(120), nullable=False)
    category_label_en: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(
        String(80), unique=True, nullable=False, index=True
    )
    name_pl: Mapped[str] = mapped_column(String(160), nullable=False)
    name_en: Mapped[str] = mapped_column(String(160), nullable=False)
    # Krótka etykieta „obszar usług" do §1 umowy.
    area_label_pl: Mapped[str] = mapped_column(String(255), nullable=False)
    area_label_en: Mapped[str] = mapped_column(String(255), nullable=False)
    # Pełny zakres obowiązków jako lista bulletów (str[]).
    scope_pl: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    scope_en: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<B2BContractRole id={self.id} slug={self.slug!r} cat={self.category_key}>"
        )
