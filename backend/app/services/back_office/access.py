"""Kto pracuje na kolejce back office'u i co widzi.

* **kierownik** — head back office (``app_settings['hr_divisions']``), jego
  zastępca (``app_settings['back_office'].deputy_user_id``) i admin: lista
  „Wszystko”, „Do przydzielenia”, przydział, skład zespołów, przegląd spraw,
* **zespół** — wiersz w ``bo_team_members``. Dopóki skład nie jest wpisany,
  zespół wynika z uprawnień (``_DEFAULT_TEAM_PERMISSIONS``), żeby włączenie
  modułu przed spisaniem listy nikogo nie odcięło,
* **kwoty** — tylko Płace i admin; „Zastępuję” kwot nie otwiera.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.back_office import BoTeamMember
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.back_office_schema import BACK_OFFICE_SETTING, TEAMS
from app.services.hr.structure import load_division_heads

_DEFAULT_TEAM_PERMISSIONS: dict[str, tuple[ProductAction, ...]] = {
    "care": (ProductAction.cases,),
    "finance": (ProductAction.payroll, ProductAction.timesheets),
    "contracts": (ProductAction.contracts_orders_edit,),
    "orders": (ProductAction.finance_module,),
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


async def lead_user_ids(db: AsyncSession) -> list[int]:
    """Head i zastępca: odbiorcy dzwonków kierownika (bez adminów z urzędu)."""

    head = (await load_division_heads(db)).get("back_office")
    deputy = (await load_settings(db)).get("deputy_user_id")
    return [uid for uid in (head, deputy) if isinstance(uid, int)]


async def load_viewer(db: AsyncSession, user: User) -> Viewer:
    is_lead = user.has_role(UserRole.admin) or user.id in await lead_user_ids(db)
    rows = (await db.execute(select(BoTeamMember.team, BoTeamMember.user_id))).all()
    teams = (
        frozenset(team for team, user_id in rows if user_id == user.id)
        if rows
        else default_teams(user)
    )
    return Viewer(
        user_id=user.id,
        teams=teams,
        is_lead=is_lead,
        sees_amounts=user.has_role(UserRole.admin)
        or has_permission(user, ProductAction.payroll),
    )


async def team_members(db: AsyncSession) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {team: [] for team in TEAMS}
    for team, user_id in (
        await db.execute(
            select(BoTeamMember.team, BoTeamMember.user_id).order_by(
                BoTeamMember.created_at, BoTeamMember.user_id
            )
        )
    ).all():
        out[team].append(user_id)
    return out
