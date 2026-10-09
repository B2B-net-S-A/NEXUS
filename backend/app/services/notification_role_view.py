"""Widok tabeli „Kto co dostaje” dla administratora (odczyt, bez zapisu).

Osobno od ``notification_role_mutes`` (reguła i zapis), bo widok dokłada
liczby z dzwonka i liczbę kont w roli — dane, których reguła nie potrzebuje.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.notification import Notification
from app.models.user import User
from app.services.notification_categories import (
    CATEGORY_INFO,
    GROUP_BY_TYPE,
    GROUP_INFO,
)
from app.services.notification_role_mutes import (
    MATRIX_ROLES,
    ROLE_LABELS,
    SETTING_KEY,
    normalise,
)

RECEIVED_WINDOW_DAYS = 30


async def _accounts_per_role(db: AsyncSession) -> dict[str, int]:
    """Aktywne konta z rolą (główną albo dodatkową)."""
    users = (await db.scalars(select(User).where(User.is_active.is_(True)))).all()
    counts = {role.value: 0 for role in MATRIX_ROLES}
    for user in users:
        for role in user.get_all_roles():
            if role.value in counts:
                counts[role.value] += 1
    return counts


async def _received(db: AsyncSession) -> dict[tuple[str, str], int]:
    """(grupa, rola główna odbiorcy) → liczba powiadomień w ostatnich 30 dniach.

    Powiadomienie liczy się raz, przy roli głównej konta — konto wielorolowe
    nie zawyża dwóch kolumn naraz.
    """
    rows = await db.execute(
        select(Notification.notification_type, User.role, func.count())
        .join(User, User.id == Notification.user_id)
        .where(
            User.is_active.is_(True),
            Notification.created_at
            >= func.now() - func.make_interval(0, 0, 0, RECEIVED_WINDOW_DAYS),
        )
        .group_by(Notification.notification_type, User.role)
    )
    received: dict[tuple[str, str], int] = {}
    for notification_type, role, count in rows.all():
        group = GROUP_BY_TYPE.get(notification_type)
        if group is None:
            continue
        key = (group, role.value)
        received[key] = received.get(key, 0) + int(count)
    return received


async def admin_view(db: AsyncSession) -> dict[str, Any]:
    row = await db.scalar(select(AppSetting).where(AppSetting.key == SETTING_KEY))
    value = normalise(row.value if row is not None else None)
    accounts = await _accounts_per_role(db)
    received = await _received(db)
    updated_by_name = None
    if row is not None and row.updated_by is not None:
        updated_by_name = await db.scalar(
            select(User.name).where(User.id == row.updated_by)
        )

    role_keys = [role.value for role in MATRIX_ROLES]
    categories = []
    for category, info in CATEGORY_INFO.items():
        groups = []
        for key, group in GROUP_INFO.items():
            if group.category != category:
                continue
            muted_at = {
                role: value["roles"].get(role, {}).get(key) for role in role_keys
            }
            groups.append(
                {
                    "key": key,
                    "label": group.label,
                    "muted": {role: muted_at[role] is not None for role in role_keys},
                    "muted_at": muted_at,
                    "received_30d": {
                        role: received.get((key, role), 0) for role in role_keys
                    },
                }
            )
        categories.append(
            {
                "key": category.value,
                "label": info.label,
                "description": info.description,
                "mandatory": info.mandatory,
                "groups": groups,
            }
        )
    return {
        "revision": value["revision"],
        "updated_at": row.updated_at.isoformat() if row is not None else None,
        "updated_by_name": updated_by_name,
        "window_days": RECEIVED_WINDOW_DAYS,
        "roles": [
            {"key": role, "label": ROLE_LABELS[role], "accounts": accounts[role]}
            for role in role_keys
        ],
        "categories": categories,
    }
