"""Kto pracuje na kolejce back office'u i co widzi.

* **kierownik** — head back office (``app_settings['hr_divisions']``), zastępca
  (rola ``deputy`` w ``bo_members``, dawniej ``app_settings['back_office']``)
  i admin: „Do przydzielenia”, przydział, skład zespołu, przegląd spraw,
* **zespół** — jeden zespół (decyzje 10.11 i 19.11.2026): wiersz w ``bo_members``
  daje wszystkie etykiety, bo sprawę bierze pierwsza wolna osoba. Dopóki skład
  nie jest wpisany, zespół wynika z uprawnień (``_DEFAULT_TEAM_PERMISSIONS``),
  żeby włączenie modułu przed spisaniem listy nikogo nie odcięło,
* **kwoty** — tylko Płace i admin; członkostwo w zespole kwot nie otwiera.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.back_office import BoMember
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.back_office_schema import BACK_OFFICE_SETTING, TEAMS
from app.services.hr.structure import load_division_heads

_DEFAULT_TEAM_PERMISSIONS: dict[str, tuple[ProductAction, ...]] = {
    "care": (ProductAction.cases,),
    "finance": (ProductAction.payroll, ProductAction.timesheets),
    "contracts": (ProductAction.contracts_orders_edit,),
    "orders": (ProductAction.orders_work,),
}


@dataclass(frozen=True)
class Viewer:
    user_id: int
    teams: frozenset[str]
    is_lead: bool
    sees_amounts: bool

    @property
    def has_access(self) -> bool:
        return self.is_lead or bool(self.teams)

    def owns(self, team: str) -> bool:
        return self.is_lead or team in self.teams


def default_teams(user: User) -> frozenset[str]:
    if user.has_role(UserRole.admin):
        return frozenset()
    return frozenset(
        team
        for team, permissions in _DEFAULT_TEAM_PERMISSIONS.items()
        if any(has_permission(user, permission) for permission in permissions)
    )


async def load_settings(db: AsyncSession) -> dict:
    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == BACK_OFFICE_SETTING)
    )
    return raw if isinstance(raw, dict) else {}


async def deputy_user_id(db: AsyncSession) -> Optional[int]:
    """Zastępca Heada: rola w składzie, a bez niej dawne ustawienie z 02.11."""

    deputy = await db.scalar(select(BoMember.user_id).where(BoMember.role == "deputy"))
    if deputy is not None:
        return deputy
    legacy = (await load_settings(db)).get("deputy_user_id")
    return legacy if isinstance(legacy, int) else None


async def lead_user_ids(db: AsyncSession) -> list[int]:
    """Head i zastępca: odbiorcy dzwonków kierownika (bez adminów z urzędu)."""

    head = (await load_division_heads(db)).get("back_office")
    deputy = await deputy_user_id(db)
    out: list[int] = []
    for uid in (head, deputy):
        if isinstance(uid, int) and uid not in out:
            out.append(uid)
    return out


async def member_ids(db: AsyncSession) -> list[int]:
    """Wpisany skład zespołu (pusty = zespół jeszcze z uprawnień)."""

    return list(
        (
            await db.scalars(
                select(BoMember.user_id).order_by(BoMember.created_at, BoMember.user_id)
            )
        ).all()
    )


async def keep_ids(db: AsyncSession) -> set[int]:
    """Kto może trzymać sprawy, choć nie jest w składzie: kierownicy i admini.

    „Sprawy u osób spoza zespołu” i „Oddaj do kolejki” ich pomijają — admin
    czy Head biorą sprawy jako kierownik, nie jako ktoś z zewnątrz.
    """

    admins = {
        user.id
        for user in (
            await db.scalars(select(User).where(User.is_active.is_(True)))
        ).all()
        if user.has_role(UserRole.admin)
    }
    return {*await member_ids(db), *await lead_user_ids(db), *admins}


async def load_viewer(db: AsyncSession, user: User) -> Viewer:
    is_lead = user.has_role(UserRole.admin) or user.id in await lead_user_ids(db)
    members = await member_ids(db)
    if members:
        teams = frozenset(TEAMS) if user.id in members else frozenset()
    else:
        teams = default_teams(user)
    return Viewer(
        user_id=user.id,
        teams=teams,
        is_lead=is_lead,
        sees_amounts=user.has_role(UserRole.admin)
        or has_permission(user, ProductAction.payroll),
    )
