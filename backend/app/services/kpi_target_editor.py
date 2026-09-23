"""Edytor celów KPI (Ustawienia → Rekrutacja → Cele KPI, plan PR3, 23.09.2026).

Do tego dnia cel zmieniał się wyłącznie przez deploy (`kpi_catalog`) albo
ręczny wiersz w bazie (audyt T5). Edytor zapisuje DOKŁADNIE te tabele, które
czyta resolver (`kpi_targets`), i tą samą regułą, którą wymusiła migracja 0346:

* zapis zawsze pod KANONICZNYM id (`canonical_kpi_id`) — wiersze aliasów tej
  samej pary są kasowane, inaczej resolver miałby dwa wiersze na jeden cel;
* odstępstwo roli równe domyślnej z katalogu = usunięcie wiersza (tabela ról
  trzyma wyłącznie świadome odstępstwa — lustro normalizacji 0346);
* osobisty cel równy domyślnemu ZOSTAJE — to decyzja o tej osobie (0346 też go
  nie kasowała); usuwa go wyłącznie jawne „Przywróć" (`None`).

Każda realna zmiana zostawia wiersz `kpi_target_events`; zapis identycznej
wartości nie zostawia nic. Po zapisie znikają cache `kpis:*` (panel zespołu,
cele liderów) — cel wyścigu i panelu liczy się przy odczycie.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import cache_invalidate
from app.models.kpi_target import KpiRoleDefault, UserKpiTarget
from app.models.kpi_target_event import KpiTargetEvent
from app.models.user import User, UserRole
from app.services.kpi_catalog import KPI_CATALOG, canonical_kpi_id, get_kpi
from app.services.kpi_targets import (
    KPI_BEARING_ROLES,
    _catalog_default,
    _ids_for,
    _prefer_canonical,
    resolve_kpi_targets_bulk,
    user_kpi_roles_clause,
)

ROLE_LABELS_PL: dict[UserRole, str] = {
    UserRole.recruiter: "Rekruter",
    UserRole.sourcer: "Sourcer",
    UserRole.tac: "TAC",
}
PERIOD_LABELS_PL = {"day": "dziennie", "week": "tygodniowo", "month": "miesięcznie"}
# Cele, które są progami Wyścigu Rekomendacji (1 500 zł) — `resolve_org_target`
# bierze maksimum domyślnych ról operacyjnych. Front ostrzega przed zapisem.
RACE_THRESHOLD_KPI_IDS = ("daily_first_verifications", "monthly_precision")


class KpiTargetEditError(ValueError):
    """Błąd walidacji z komunikatem po polsku dla użytkownika (422)."""


@dataclass(frozen=True)
class EditResult:
    changed: bool
    previous: Optional[int]
    stored: Optional[int]


def _known_kpi(kpi_id: str) -> str:
    kpi = get_kpi(kpi_id)
    if kpi is None:
        raise KpiTargetEditError(f"Nieznany wskaźnik KPI: {kpi_id}")
    return kpi.kpi_id


def _role(value: str) -> UserRole:
    try:
        role = UserRole(value)
    except ValueError as exc:
        raise KpiTargetEditError(f"Nieznana rola: {value}") from exc
    if role not in KPI_BEARING_ROLES:
        raise KpiTargetEditError(
            "Cele KPI mają wyłącznie role rekrutacyjne: rekruter, sourcer, TAC."
        )
    return role


def _check_value(value: Optional[int]) -> None:
    if value is not None and (value < 0 or value > 100_000):
        raise KpiTargetEditError("Cel musi być liczbą od 0 do 100 000.")


def _actor_name(user: User) -> str:
    return user.name or user.email or f"#{user.id}"


async def set_role_default(
    db: AsyncSession,
    *,
    role: str,
    kpi_id: str,
    target_value: Optional[int],
    actor: User,
) -> EditResult:
    """Ustaw (albo zdejmij) odstępstwo roli od katalogu. Commit robi wołający."""
    canonical = _known_kpi(kpi_id)
    role_enum = _role(role)
    _check_value(target_value)
    ids = _ids_for(canonical)
    rows = (
        await db.execute(
            select(KpiRoleDefault.kpi_id, KpiRoleDefault.target_value)
            .where(
                KpiRoleDefault.role == role_enum,
                KpiRoleDefault.kpi_id.in_(ids),
            )
            .with_for_update()
        )
    ).all()
    previous = _prefer_canonical(
        [(r.kpi_id, int(r.target_value)) for r in rows], canonical
    )
    catalog = _catalog_default(canonical, role_enum)
    stored = None if target_value is None or target_value == catalog else target_value
    only_canonical = all(r.kpi_id == canonical for r in rows)
    if previous == stored and only_canonical and len(rows) <= 1:
        return EditResult(changed=False, previous=previous, stored=stored)
    await db.execute(
        delete(KpiRoleDefault).where(
            KpiRoleDefault.role == role_enum, KpiRoleDefault.kpi_id.in_(ids)
        )
    )
    if stored is not None:
        db.add(KpiRoleDefault(role=role_enum, kpi_id=canonical, target_value=stored))
    if previous != stored:
        db.add(
            KpiTargetEvent(
                scope="role",
                role=role_enum.value,
                kpi_id=canonical,
                action="reset" if stored is None else "set",
                changes={
                    "target_value": {"from": previous, "to": stored},
                    "catalog_default": catalog,
                },
                actor_user_id=actor.id,
                actor_name=_actor_name(actor),
            )
        )
    await db.flush()
    return EditResult(changed=previous != stored, previous=previous, stored=stored)


async def set_user_target(
    db: AsyncSession,
    *,
    user_id: int,
    kpi_id: str,
    target_value: Optional[int],
    actor: User,
) -> EditResult:
    """Ustaw (albo zdejmij `None`) osobisty cel. Commit robi wołający."""
    canonical = _known_kpi(kpi_id)
    _check_value(target_value)
    subject = await db.get(User, user_id)
    if subject is None:
        raise LookupError("user_not_found")
    ids = _ids_for(canonical)
    rows = (
        await db.execute(
            select(UserKpiTarget.kpi_id, UserKpiTarget.target_value)
            .where(UserKpiTarget.user_id == user_id, UserKpiTarget.kpi_id.in_(ids))
            .with_for_update()
        )
    ).all()
    previous = _prefer_canonical(
        [(r.kpi_id, int(r.target_value)) for r in rows], canonical
    )
    only_canonical = all(r.kpi_id == canonical for r in rows)
    if previous == target_value and only_canonical and len(rows) <= 1:
        return EditResult(changed=False, previous=previous, stored=target_value)
    await db.execute(
        delete(UserKpiTarget).where(
            UserKpiTarget.user_id == user_id, UserKpiTarget.kpi_id.in_(ids)
        )
    )
    if target_value is not None:
        db.add(
            UserKpiTarget(user_id=user_id, kpi_id=canonical, target_value=target_value)
        )
    if previous != target_value:
        db.add(
            KpiTargetEvent(
                scope="user",
                subject_user_id=subject.id,
                subject_name=subject.name or subject.email,
                kpi_id=canonical,
                action="reset" if target_value is None else "set",
                changes={"target_value": {"from": previous, "to": target_value}},
                actor_user_id=actor.id,
                actor_name=_actor_name(actor),
            )
        )
    await db.flush()
    return EditResult(
        changed=previous != target_value, previous=previous, stored=target_value
    )


async def invalidate_target_caches() -> None:
    await cache_invalidate("kpis:")


async def build_matrix(db: AsyncSession) -> dict:
    """Macierz rola × KPI + efektywne cele każdej osoby z rolą rekrutacyjną."""
    kpis = [
        {
            "kpi_id": k.kpi_id,
            "title": k.title_pl,
            "description": k.description_pl,
            "period": k.period.value,
            "period_label": PERIOD_LABELS_PL[k.period.value],
            "race_threshold": k.kpi_id in RACE_THRESHOLD_KPI_IDS,
        }
        for k in KPI_CATALOG
    ]
    kpi_ids = [k.kpi_id for k in KPI_CATALOG]
    all_ids = sorted({i for k in kpi_ids for i in _ids_for(k)})

    role_rows = (
        await db.execute(
            select(
                KpiRoleDefault.role, KpiRoleDefault.kpi_id, KpiRoleDefault.target_value
            ).where(
                KpiRoleDefault.role.in_(KPI_BEARING_ROLES),
                KpiRoleDefault.kpi_id.in_(all_ids),
            )
        )
    ).all()
    by_role: dict[tuple[UserRole, str], list[tuple[str, int]]] = {}
    for row in role_rows:
        by_role.setdefault((row.role, canonical_kpi_id(row.kpi_id)), []).append(
            (row.kpi_id, int(row.target_value))
        )
    roles = []
    for role in KPI_BEARING_ROLES:
        cells = {}
        for kpi_id in kpi_ids:
            catalog = _catalog_default(kpi_id, role)
            override = _prefer_canonical(by_role.get((role, kpi_id), ()), kpi_id)
            cells[kpi_id] = {
                "catalog_default": catalog,
                "override": override,
                "effective": catalog if override is None else override,
            }
        roles.append(
            {"role": role.value, "label": ROLE_LABELS_PL[role], "targets": cells}
        )

    users = (
        (
            await db.execute(
                select(User)
                .where(User.is_active.is_(True), user_kpi_roles_clause())
                .order_by(User.name, User.id)
            )
        )
        .scalars()
        .all()
    )
    effective = await resolve_kpi_targets_bulk(db, users, kpi_ids)
    user_ids = [u.id for u in users]
    overrides: dict[tuple[int, str], list[tuple[str, int]]] = {}
    if user_ids:
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
            overrides.setdefault(
                (int(row.user_id), canonical_kpi_id(row.kpi_id)), []
            ).append((row.kpi_id, int(row.target_value)))
    people = []
    for user in users:
        cells = {}
        for kpi_id in kpi_ids:
            personal = _prefer_canonical(overrides.get((user.id, kpi_id), ()), kpi_id)
            cells[kpi_id] = {
                "effective": effective[user.id][kpi_id],
                "override": personal,
                "source": "user" if personal is not None else "role",
            }
        people.append(
            {
                "user_id": user.id,
                "name": user.name or user.email,
                "roles": sorted(
                    r.value for r in user.get_all_roles() if r in KPI_BEARING_ROLES
                ),
                "targets": cells,
            }
        )
    return {"kpis": kpis, "roles": roles, "users": people}


async def history(db: AsyncSession, *, limit: int = 50) -> list[dict]:
    rows = (
        (
            await db.execute(
                select(KpiTargetEvent)
                .order_by(KpiTargetEvent.created_at.desc(), KpiTargetEvent.id.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    titles = {k.kpi_id: k.title_pl for k in KPI_CATALOG}
    out = []
    for ev in rows:
        change = (ev.changes or {}).get("target_value") or {}
        role_label = None
        if ev.role:
            try:
                role_label = ROLE_LABELS_PL.get(UserRole(ev.role), ev.role)
            except ValueError:
                role_label = ev.role
        out.append(
            {
                "id": ev.id,
                "scope": ev.scope,
                "role": ev.role,
                "role_label": role_label,
                "subject_user_id": ev.subject_user_id,
                "subject_name": ev.subject_name,
                "kpi_id": ev.kpi_id,
                "kpi_title": titles.get(ev.kpi_id, ev.kpi_id),
                "action": ev.action,
                "from_value": change.get("from"),
                "to_value": change.get("to"),
                "actor_name": ev.actor_name,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
        )
    return out
