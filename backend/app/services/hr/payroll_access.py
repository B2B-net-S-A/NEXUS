"""Kto co widzi w Płacach (decyzja Artura D2, 16.10.2026).

* **Płace** (uprawnienie ``payroll``; Finanse z roli, admin zawsze) — stawki,
  kwoty, premie, zamknięcie miesiąca u wszystkich,
* **osoba** — swoje stawki, godziny i premie,
* **przełożony** (bezpośredni, z kartoteki) — godziny i premie swoich ludzi,
  BEZ stawek i kwot wynagrodzenia; przyznaje premię ręczną swojemu
  człowiekowi i decyduje o propozycjach automatów dla niego,
* nikt — premii dla samego siebie (CHECK-i w bazie i odmowa tutaj).

Compass pozwalał KAŻDEMU managerowi zmienić, potwierdzić albo usunąć
dowolny placement i wygenerować premie osobom spoza zespołu — tu zakres
przełożonego to wyłącznie jego bezpośredni podwładni.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import people


def is_payroll(user: User) -> bool:
    return user.has_role(UserRole.admin) or has_permission(user, ProductAction.payroll)


@dataclass(frozen=True)
class PayrollViewer:
    user_id: int
    payroll: bool
    admin: bool
    report_ids: frozenset[int]

    def sees_rates_of(self, subject_id: int) -> bool:
        """Stawki i kwoty wynagrodzenia: Płace i sama osoba."""

        return self.payroll or subject_id == self.user_id

    def sees_person(self, subject_id: int) -> bool:
        """Godziny i premie: Płace, sama osoba, jej przełożony."""

        return (
            self.payroll or subject_id == self.user_id or subject_id in self.report_ids
        )

    def manages_bonuses_of(self, recipient_id: int) -> bool:
        """Przyznanie i decyzja o premii: Płace albo przełożony — nigdy dla siebie."""

        if recipient_id == self.user_id:
            return False
        return self.payroll or recipient_id in self.report_ids

    @property
    def is_manager(self) -> bool:
        return bool(self.report_ids)


async def load_viewer(db: AsyncSession, user: User) -> PayrollViewer:
    return PayrollViewer(
        user_id=user.id,
        payroll=is_payroll(user),
        admin=user.has_role(UserRole.admin),
        report_ids=frozenset(await people.direct_report_ids(db, user.id)),
    )


__all__ = ["PayrollViewer", "is_payroll", "load_viewer"]
