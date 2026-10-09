"""Powiadomienia wyłączone dla całej roli — tabela „Kto co dostaje” (09.10.2026).

Do tej daty jedynym wyłącznikiem dzwonka były wyciszenia OSOBY (0349), więc
administrator nie miał jak powiedzieć „admini nie dostają końca zamówień”:
każde z kont musiało kliknąć samo, a wyciszenia miało 1 konto z 34.

Stan żyje w jednym wierszu ``app_settings['notification_role_mutes']``::

    {"revision": 3, "roles": {"admin": {"contracts_order_ending": "<kiedy>"}}}

Znacznik czasu służy temu samemu co przy wyciszeniach osoby: po ponownym
włączeniu grupy powiadomienia z czasu wyłączenia są oznaczane jako przeczytane,
żeby nie wróciły jako fala zaległości.

Konto wielorolowe ma grupę wyłączoną dopiero wtedy, gdy jest wyłączona
w KAŻDEJ jego roli — tak jak sekcje liczą się z maksimum ról. Inaczej Head of
Recruitment z dodatkową rolą rekrutera traciłby powiadomienia rekrutera.

Wyłączenie stosuje ``notification_access`` (to samo miejsce co wyciszenia
osoby); tu jest tylko odczyt, zapis i czysta reguła. Wiersz czytamy przy
każdym liczeniu dostępu, bez pamięci procesu — jak resztę polityki
(``effective_access``), żeby zmiana działała od następnego żądania.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.services.critical_events import record_executed
from app.services.notification_categories import (
    GROUP_INFO,
    group_is_mutable,
    types_in_group,
)

SETTING_KEY = "notification_role_mutes"
EVENT_TYPE = "notifications.role_mutes"

# Kolumny tabeli. Viewer i praktykant nie mają sekcji, więc nie mają czego
# wyłączać; rola spoza listy nigdy nie ma nic wyłączonego.
MATRIX_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.recruiter,
    UserRole.talent_community_manager,
    UserRole.finance,
)

ROLE_LABELS: dict[str, str] = {
    UserRole.admin.value: "Admin",
    UserRole.head_of_recruitment.value: "Head of Recruitment",
    UserRole.delivery_lead.value: "Delivery Lead",
    UserRole.recruiter.value: "Rekruter",
    UserRole.talent_community_manager.value: "Talent Community Manager",
    UserRole.finance.value: "Finanse",
}

_MATRIX_ROLE_VALUES = frozenset(role.value for role in MATRIX_ROLES)


class StaleRoleMutes(Exception):
    """Ktoś zapisał tabelę wcześniej — klient ma starą wersję."""


@dataclass(frozen=True)
class RoleMuteChange:
    role: str
    group: str
    muted: bool


def normalise(raw: Any) -> dict[str, Any]:
    """Zapis bywa starszy niż kod — czytamy go łagodnie.

    Nieznana rola, nieznana grupa i grupa z kategorii obowiązkowej są
    pomijane: nigdy nie wyłączamy czegoś, czego dziś wyłączyć nie wolno.
    """
    value = raw if isinstance(raw, Mapping) else {}
    revision = value.get("revision")
    roles_raw = value.get("roles")
    roles: dict[str, dict[str, str]] = {}
    if isinstance(roles_raw, Mapping):
        for role, groups in roles_raw.items():
            if role not in _MATRIX_ROLE_VALUES or not isinstance(groups, Mapping):
                continue
            kept = {
                group: str(muted_at)
                for group, muted_at in groups.items()
                if group_is_mutable(group) and muted_at
            }
            if kept:
                roles[role] = kept
    return {
        "revision": revision if isinstance(revision, int) and revision >= 0 else 0,
        "roles": roles,
    }


def _role_values(roles: Iterable[UserRole | str]) -> set[str]:
    return {role.value if isinstance(role, UserRole) else str(role) for role in roles}


def role_muted_groups(
    value: Mapping[str, Any], roles: Iterable[UserRole | str]
) -> frozenset[str]:
    """Grupy wyłączone we WSZYSTKICH rolach konta (``value`` po ``normalise``)."""
    role_values = _role_values(roles)
    if not role_values:
        return frozenset()
    stored: Mapping[str, Mapping[str, str]] = value.get("roles", {})
    common: set[str] | None = None
    for role in role_values:
        groups = set(stored.get(role, {}))
        common = groups if common is None else common & groups
        if not common:
            return frozenset()
    return frozenset(common or ())


def role_muted_types(
    value: Mapping[str, Any], roles: Iterable[UserRole | str]
) -> frozenset[NotificationType]:
    muted: set[NotificationType] = set()
    for group in role_muted_groups(value, roles):
        muted |= types_in_group(group)
    return frozenset(muted)


async def load_value(db: AsyncSession) -> dict[str, Any]:
    # `scalars(...).all()` jak pozostałe odczyty polityki w `effective_access`:
    # atrapy sesji w testach kierują je po encji, a liczniki `db.scalar`
    # należą do kodu, który ten resolver woła.
    rows = (
        await db.scalars(select(AppSetting).where(AppSetting.key == SETTING_KEY))
    ).all()
    return normalise(rows[0].value if rows else None)


async def attach_role_mutes(db: AsyncSession, users: Iterable[User]) -> None:
    """Dołącz do kont typy wyłączone dla ich ról (czyta ``notification_access``)."""
    user_list = list(users)
    if not user_list:
        return
    value = await load_value(db)
    for user in user_list:
        user.role_muted_notification_types = (
            role_muted_types(value, user.get_all_roles())
            if value["roles"]
            else frozenset()
        )


async def _accounts_with_role(db: AsyncSession, role: str) -> list[User]:
    return list(
        (
            await db.scalars(
                select(User).where(
                    User.is_active.is_(True),
                    or_(User.role == role, User.roles.contains([role])),
                )
            )
        ).all()
    )


async def _mark_read_after_unmute(
    db: AsyncSession,
    *,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    role: str,
    group: str,
    muted_at: str,
) -> None:
    """Powiadomienia z czasu wyłączenia nie wracają jako nieprzeczytane.

    Tylko konta, którym grupa była naprawdę wyłączona i właśnie przestała być
    (konto z drugą rolą, w której grupa była włączona, widziało je cały czas).
    """
    try:
        since = datetime.fromisoformat(muted_at)
    except ValueError:
        return
    user_ids = [
        user.id
        for user in await _accounts_with_role(db, role)
        if group in role_muted_groups(before, user.get_all_roles())
        and group not in role_muted_groups(after, user.get_all_roles())
    ]
    if not user_ids:
        return
    await db.execute(
        update(Notification)
        .where(
            Notification.user_id.in_(user_ids),
            Notification.is_read.is_(False),
            Notification.notification_type.in_(sorted(types_in_group(group), key=str)),
            Notification.created_at >= since,
        )
        .values(is_read=True)
    )


def _summary(role: str, changes: Mapping[str, Mapping[str, bool]]) -> str:
    off = [GROUP_INFO[g].label for g, c in changes.items() if c["to"]]
    on = [GROUP_INFO[g].label for g, c in changes.items() if not c["to"]]
    parts = []
    if off:
        parts.append("wyłączono: " + ", ".join(off))
    if on:
        parts.append("włączono: " + ", ".join(on))
    return f"Powiadomienia roli {ROLE_LABELS[role]} — " + "; ".join(parts)


async def save_changes(
    db: AsyncSession,
    *,
    actor: User,
    revision: int,
    changes: Iterable[RoleMuteChange],
) -> dict[str, Any]:
    """Zapisz zmiany pod blokadą wiersza. Commit należy do wołającego."""
    await db.execute(
        insert(AppSetting)
        .values(key=SETTING_KEY, value={"revision": 0, "roles": {}})
        .on_conflict_do_nothing(index_elements=[AppSetting.key])
    )
    row = await db.scalar(
        select(AppSetting)
        .where(AppSetting.key == SETTING_KEY)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert row is not None
    before = normalise(row.value)
    if before["revision"] != revision:
        raise StaleRoleMutes

    now = datetime.now(timezone.utc).isoformat()
    after_roles = {role: dict(groups) for role, groups in before["roles"].items()}
    applied: dict[str, dict[str, dict[str, bool]]] = {}
    unmuted: list[tuple[str, str, str]] = []
    for change in changes:
        groups = after_roles.setdefault(change.role, {})
        was_muted = change.group in groups
        if was_muted == change.muted:
            continue
        if change.muted:
            groups[change.group] = now
        else:
            unmuted.append((change.role, change.group, groups.pop(change.group)))
        applied.setdefault(change.role, {})[change.group] = {
            "from": was_muted,
            "to": change.muted,
        }
    if not applied:
        return before

    after = normalise({"revision": before["revision"] + 1, "roles": after_roles})
    row.value = after
    row.updated_by = actor.id
    await db.flush()

    for role, group, muted_at in unmuted:
        await _mark_read_after_unmute(
            db, before=before, after=after, role=role, group=group, muted_at=muted_at
        )
    for role, role_changes in applied.items():
        await record_executed(
            db,
            actor=actor,
            event_type=EVENT_TYPE,
            entity_type="role",
            entity_id=None,
            entity_label=ROLE_LABELS[role],
            reason=_summary(role, role_changes),
            details={
                "role": role,
                "revision": after["revision"],
                "changes": role_changes,
            },
        )
    return after
