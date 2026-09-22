"""KPI Coach — targety (per-rola default + per-user override).

Definicje KPI i domyślne liczby żyją w kodzie (`app/services/kpi_catalog.py`,
jedyny katalog od 22.09.2026). Tabele trzymają wyłącznie ODSTĘPSTWA od katalogu
(po migracji 0343 `kpi_role_defaults` jest pusta). W aplikacji nie ma ekranu,
który je zapisuje (audyt T5) — zmiana celu to dziś zmiana katalogu albo wiersz
wpisany ręcznie.

Precedencja (`app/services/kpi_targets.py`):
  user_kpi_targets → dla KAŻDEJ roli osoby kpi_role_defaults albo
  KpiDef.default_targets[rola] → maksimum z ról → 0.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.user import UserRole


class KpiRoleDefault(Base, TimestampMixin):
    """Odstępstwo od domyślnego celu katalogu dla pary (role, kpi_id)."""

    __tablename__ = "kpi_role_defaults"
    __table_args__ = (
        UniqueConstraint("role", "kpi_id", name="uq_kpi_role_defaults_role_kpi"),
        CheckConstraint("target_value >= 0", name="ck_kpi_role_defaults_target_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="userrole"), nullable=False
    )
    kpi_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_value: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<KpiRoleDefault role={self.role.value} kpi={self.kpi_id} "
            f"target={self.target_value}>"
        )


class UserKpiTarget(Base, TimestampMixin):
    """Per-user override target_value dla kpi_id. Nadpisuje role default."""

    __tablename__ = "user_kpi_targets"
    __table_args__ = (
        UniqueConstraint("user_id", "kpi_id", name="uq_user_kpi_targets_user_kpi"),
        CheckConstraint("target_value >= 0", name="ck_user_kpi_targets_target_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kpi_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_value: Mapped[int] = mapped_column(Integer, nullable=False)

    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return (
            f"<UserKpiTarget user={self.user_id} kpi={self.kpi_id} "
            f"target={self.target_value}>"
        )
