"""Opieka · pula opiekunów (decyzja Artura 18.10.2026).

Opiekunem konsultanta może być każda osoba podlegająca bezpośrednio pod
wskazanego przełożonego w kartotece („Ludzie”, ``employee_profiles.manager_user_id``)
— dziś ludzie Finansów i TCM pod head back office. Pula jest WYLICZANA ze
struktury przy każdym odczycie; w ustawieniu leżą tylko:

* ``manager_user_id`` — czyi podwładni tworzą pulę (brak klucza = head back
  office z ``app_settings['hr_divisions']``, ``null`` = puli nie ma),
* ``excluded_user_ids`` — osoby, którym nie przypisujemy konsultantów ani
  automatem, ani ręcznie (np. księgowość),
* ``auto_new_contracts`` — nowy kontrakt dostaje opiekuna wg obłożenia
  (domyślnie tak).

Członek puli (niewykluczony) może być opiekunem i prowadzić opiekę jak TCM,
także bez roli DL/TCM/admin (``care_access.is_care_writer``). Automat
przydziela tylko tym, którzy widzą opiekę (sekcja i podgląd Delivery) —
inaczej przypomnienie prowadziłoby na 403.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import audit
from app.services.hr_foundation_schema import EmploymentStatus

POOL_SETTING = "care_owner_pool"
EXCLUDED_MAX = 100
#: Kto z kartoteki trafia do puli: pracuje, nie kończy (kończącemu nie dajemy nowych).
POOL_STATUSES: tuple[str, ...] = (
    EmploymentStatus.onboarding.value,
    EmploymentStatus.active.value,
)

NO_CARE_ACCESS = "nie widzi Opieki (brak sekcji albo podglądu Delivery)"
MANAGER_INVALID = "Przełożony puli musi mieć aktywne konto."
EXCLUDED_INVALID = "Na liście wykluczonych są nieznane konta."


@dataclass(frozen=True)
class PoolConfig:
    manager_user_id: Optional[int]
    excluded_user_ids: tuple[int, ...]
    auto_new_contracts: bool
    #: ``True`` = przełożony wzięty z head back office (nikt go nie wskazał).
    manager_from_division: bool = False


@dataclass(frozen=True)
class PoolMember:
    user: User
    excluded: bool
    sees_care: bool

    @property
    def eligible(self) -> bool:
        """Automat może przypisać tej osobie konsultanta."""

        return not self.excluded and self.sees_care


def _positive_int(value: Any) -> Optional[int]:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else None
    )


async def load_config(db: AsyncSession) -> PoolConfig:
    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == POOL_SETTING)
    )
    raw = raw if isinstance(raw, dict) else {}
    excluded = tuple(
        sorted({v for v in (raw.get("excluded_user_ids") or []) if _positive_int(v)})
    )
    auto = raw.get("auto_new_contracts")
    if "manager_user_id" in raw:
        return PoolConfig(
            _positive_int(raw.get("manager_user_id")), excluded, auto is not False
        )
    from app.services.hr.structure import load_division_heads  # noqa: PLC0415

    head = (await load_division_heads(db)).get("back_office")
    return PoolConfig(head, excluded, auto is not False, manager_from_division=True)


async def save_config(
    db: AsyncSession,
    *,
    manager_user_id: Optional[int],
    excluded_user_ids: list[int],
    auto_new_contracts: bool,
    actor: User,
) -> PoolConfig:
    """Zapis ustawienia (bez commita); ślad ``care.owner_pool_set`` (same id)."""

    if manager_user_id is not None:
        manager = await db.get(User, manager_user_id)
        if manager is None or not manager.is_active:
            raise ValueError(MANAGER_INVALID)
    excluded = sorted(set(excluded_user_ids))
    if excluded:
        known = set(await db.scalars(select(User.id).where(User.id.in_(excluded))))
        if known != set(excluded):
            raise ValueError(EXCLUDED_INVALID)
    previous = await load_config(db)
    payload = {
        "manager_user_id": manager_user_id,
        "excluded_user_ids": excluded,
        "auto_new_contracts": auto_new_contracts,
    }
    await db.execute(
        pg_insert(AppSetting)
        .values(key=POOL_SETTING, value=payload, updated_by=actor.id)
        .on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": payload, "updated_by": actor.id},
        )
    )
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="app_setting",
        entity_id=POOL_SETTING,
        action="care.owner_pool_set",
        details={
            "previous": {
                "manager_user_id": previous.manager_user_id,
                "excluded_user_ids": list(previous.excluded_user_ids),
                "auto_new_contracts": previous.auto_new_contracts,
            },
            "value": payload,
        },
    )
    return PoolConfig(manager_user_id, tuple(excluded), auto_new_contracts)


def _sees_care(user: User) -> bool:
    from app.services.action_permissions import ProductAction, has_permission  # noqa: PLC0415
    from app.services.section_permissions import (  # noqa: PLC0415
        ProductSection,
        SectionAccess,
        section_access_for_user,
    )

    return has_permission(user, ProductAction.delivery_view) and (
        section_access_for_user(user, ProductSection.delivery) >= SectionAccess.read
    )


async def members(
    db: AsyncSession, config: Optional[PoolConfig] = None
) -> list[PoolMember]:
    """Bezpośredni podwładni przełożonego puli (aktywne konta), po nazwisku."""

    config = config or await load_config(db)
    if config.manager_user_id is None:
        return []
    users = list(
        (
            await db.scalars(
                select(User)
                .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
                .where(
                    EmployeeProfile.manager_user_id == config.manager_user_id,
                    EmployeeProfile.employment_status.in_(POOL_STATUSES),
                    User.is_active.is_(True),
                    User.id != config.manager_user_id,
                )
            )
        ).all()
    )
    if not users:
        return []
    from app.services.effective_access import resolve_effective_access  # noqa: PLC0415

    await resolve_effective_access(db, users)
    excluded = set(config.excluded_user_ids)
    out = [
        PoolMember(user=user, excluded=user.id in excluded, sees_care=_sees_care(user))
        for user in users
    ]
    return sorted(out, key=lambda m: ((m.user.name or "").casefold(), m.user.id))


async def writer_ids(db: AsyncSession) -> frozenset[int]:
    """Niewykluczeni członkowie puli — prowadzą opiekę jak TCM."""

    config = await load_config(db)
    if config.manager_user_id is None:
        return frozenset()
    rows = await db.scalars(
        select(EmployeeProfile.user_id)
        .join(User, User.id == EmployeeProfile.user_id)
        .where(
            EmployeeProfile.manager_user_id == config.manager_user_id,
            EmployeeProfile.employment_status.in_(POOL_STATUSES),
            User.is_active.is_(True),
        )
    )
    return frozenset(set(rows.all()) - set(config.excluded_user_ids))


async def excluded_ids(db: AsyncSession) -> frozenset[int]:
    return frozenset((await load_config(db)).excluded_user_ids)


async def manager_choices(db: AsyncSession) -> list[dict[str, Any]]:
    """Przełożeni z kartoteki (aktywne konta, które mają podwładnych)."""

    rows = (
        await db.execute(
            select(User.id, User.name)
            .where(
                User.is_active.is_(True),
                User.id.in_(
                    select(EmployeeProfile.manager_user_id).where(
                        EmployeeProfile.manager_user_id.is_not(None)
                    )
                ),
            )
            .order_by(User.name)
        )
    ).all()
    return [{"id": uid, "name": name} for uid, name in rows]
