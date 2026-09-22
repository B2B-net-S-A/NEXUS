"""Rozstrzyganie celów KPI — JEDNA reguła dla całego repo (22.09.2026).

Czytają ją: widget KPI Coach (`kpi_engine`), panel „Moje KPI" (`kpi_panel`),
postęp dnia na pulpicie (`recruitment_activity`), nudge'e (`kpi_coach_service`),
wyścig miesięczny (`competitions`), panel zespołu (`kpi_team`), raport Power
Calling (`api/reports`) i cele liderów (`kpi_goals`).

Reguła:

1. **Osobisty cel** (`user_kpi_targets`) wygrywa zawsze.
2. W przeciwnym razie cel liczony jest dla **KAŻDEJ roli osoby**
   (`User.get_all_roles()` — główna i dodatkowe): wiersz `kpi_role_defaults`
   dla tej roli, a bez wiersza domyślna liczba z `kpi_catalog`.
3. Z ról bierzemy **MAKSIMUM**. Osoba z główną rolą `delivery_lead` i dodatkową
   `tac` realnie rekrutuje — do 22.09 dostawała cel 0 (liczony z roli głównej)
   i widget nic jej nie pokazywał, choć wpuszczał ją na tej samej podstawie.
   Maksimum, a nie suma: dwie role rekrutacyjne to jedna praca, nie dwie.

Cel „organizacyjny" (wyścig, panel zespołu, raport Power Calling) to ta sama
reguła zastosowana do ról operacyjnych — `resolve_org_target`. Dzięki temu
zmiana celu weryfikacji w jednym miejscu zmienia próg wyścigu z nagrodą,
cel precyzji w panelu zespołu i próg raportu, a nie tylko widget.

Identyfikatory panelu sprzed 22.09 (`verifications_daily` itd.) są aliasami
(`kpi_catalog.KPI_ID_ALIASES`) — wiersz zapisany pod starym id nadal działa,
choć wiersz pod id kanonicznym ma pierwszeństwo.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.kpi_target import KpiRoleDefault, UserKpiTarget
from app.models.user import User, UserRole
from app.services.kpi_catalog import KPI_ID_ALIASES, canonical_kpi_id, get_kpi

# Role z osobistymi celami rekrutacyjnymi (i pula celu organizacyjnego).
KPI_BEARING_ROLES: tuple[UserRole, ...] = (
    UserRole.recruiter,
    UserRole.sourcer,
    UserRole.tac,
)


def _ids_for(kpi_id: str) -> tuple[str, ...]:
    """Kanoniczny id + wszystkie jego aliasy (kanoniczny pierwszy)."""
    canonical = canonical_kpi_id(kpi_id)
    return (canonical,) + tuple(
        alias for alias, target in KPI_ID_ALIASES.items() if target == canonical
    )


def _prefer_canonical(rows: Iterable[tuple[str, int]], canonical: str) -> int | None:
    """Z wierszy (kpi_id, wartość) jednego klucza: kanoniczny przed aliasem."""
    best: int | None = None
    for kpi_id, value in rows:
        if kpi_id == canonical:
            return int(value)
        if best is None:
            best = int(value)
    return best


def _catalog_default(kpi_id: str, role: UserRole) -> int:
    kpi = get_kpi(kpi_id)
    if kpi is None:
        return 0
    return int(kpi.default_targets.get(role, 0))


def user_kpi_roles_clause(roles: Sequence[UserRole] = KPI_BEARING_ROLES):
    """WHERE „osoba ma KTÓRĄKOLWIEK z ról" — główną albo dodatkową."""
    return or_(
        User.role.in_(tuple(roles)),
        *(User.roles.contains([role.value]) for role in roles),
    )


async def resolve_kpi_targets_bulk(
    db: AsyncSession, users: Sequence[User], kpi_ids: Sequence[str]
) -> dict[int, dict[str, int]]:
    """Cele wielu osób naraz: `{user_id: {kanoniczny_kpi_id: cel}}`.

    Dwa zapytania niezależnie od liczby osób i KPI — panel zespołu liderów
    liczy cel dla każdego członka zespołu.
    """
    canonical_ids = [canonical_kpi_id(k) for k in kpi_ids]
    all_ids = sorted({i for k in canonical_ids for i in _ids_for(k)})
    user_ids = [u.id for u in users]
    roles_by_user = {u.id: u.get_all_roles() for u in users}
    all_roles = sorted({r for roles in roles_by_user.values() for r in roles})

    overrides: dict[tuple[int, str], list[tuple[str, int]]] = {}
    if user_ids and all_ids:
        for row in (
            await db.execute(
                select(
                    UserKpiTarget.user_id,
                    UserKpiTarget.kpi_id,
                    UserKpiTarget.target_value,
                ).where(
                    UserKpiTarget.user_id.in_(user_ids),
                    UserKpiTarget.kpi_id.in_(all_ids),
                )
            )
        ).all():
            key = (int(row.user_id), canonical_kpi_id(row.kpi_id))
            overrides.setdefault(key, []).append((row.kpi_id, int(row.target_value)))

    role_rows: dict[tuple[UserRole, str], list[tuple[str, int]]] = {}
    if all_roles and all_ids:
        for row in (
            await db.execute(
                select(
                    KpiRoleDefault.role,
                    KpiRoleDefault.kpi_id,
                    KpiRoleDefault.target_value,
                ).where(
                    KpiRoleDefault.role.in_(all_roles),
                    KpiRoleDefault.kpi_id.in_(all_ids),
                )
            )
        ).all():
            key = (row.role, canonical_kpi_id(row.kpi_id))
            role_rows.setdefault(key, []).append((row.kpi_id, int(row.target_value)))

    out: dict[int, dict[str, int]] = {}
    for user in users:
        per_kpi: dict[str, int] = {}
        for canonical in canonical_ids:
            override = _prefer_canonical(
                overrides.get((user.id, canonical), ()), canonical
            )
            if override is not None:
                per_kpi[canonical] = override
                continue
            best = 0
            for role in roles_by_user[user.id]:
                db_value = _prefer_canonical(
                    role_rows.get((role, canonical), ()), canonical
                )
                value = (
                    db_value
                    if db_value is not None
                    else _catalog_default(canonical, role)
                )
                best = max(best, value)
            per_kpi[canonical] = best
        out[user.id] = per_kpi
    return out


async def resolve_kpi_target(db: AsyncSession, *, user: User, kpi_id: str) -> int:
    """Cel jednej osoby dla jednego KPI (reguła z docstringa modułu)."""
    targets = await resolve_kpi_targets_bulk(db, [user], [kpi_id])
    return targets[user.id][canonical_kpi_id(kpi_id)]


async def resolve_org_target(
    db: AsyncSession,
    kpi_id: str,
    *,
    roles: Sequence[UserRole] = KPI_BEARING_ROLES,
) -> int:
    """Cel organizacyjny: maksimum celu ról operacyjnych (bez osobistych).

    Próg wyścigu miesięcznego, cel precyzji panelu zespołu i próg raportu
    Power Calling — wszystkie mówią „jeden cel dla całego zespołu", a nie cel
    konkretnej osoby. Liczymy go tą samą regułą co cel osoby z wszystkimi
    rolami operacyjnymi naraz.
    """
    canonical = canonical_kpi_id(kpi_id)
    ids = _ids_for(canonical)
    rows = (
        await db.execute(
            select(
                KpiRoleDefault.role,
                KpiRoleDefault.kpi_id,
                KpiRoleDefault.target_value,
            ).where(
                KpiRoleDefault.role.in_(tuple(roles)),
                KpiRoleDefault.kpi_id.in_(ids),
            )
        )
    ).all()
    by_role: dict[UserRole, list[tuple[str, int]]] = {}
    for row in rows:
        by_role.setdefault(row.role, []).append((row.kpi_id, int(row.target_value)))
    best = 0
    for role in roles:
        db_value = _prefer_canonical(by_role.get(role, ()), canonical)
        best = max(
            best,
            db_value if db_value is not None else _catalog_default(canonical, role),
        )
    return best


__all__ = [
    "KPI_BEARING_ROLES",
    "resolve_kpi_target",
    "resolve_kpi_targets_bulk",
    "resolve_org_target",
    "user_kpi_roles_clause",
]
