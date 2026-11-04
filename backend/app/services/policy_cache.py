"""Bufor polityki dostępu w procesie (decyzja Artura 04.11.2026).

Pomiar 04.11.2026: trasy są wolne przez kolejkę w jednym wątku Pythona, a 48%
instrukcji SQL to autoryzacja i ustawienia. Komplet polityki zmienia się rzadko,
więc jedna migawka tabel obsługuje wszystkie żądania i pętle tego procesu.

Migawka trzyma same wartości, nigdy obiekty ORM, i ma trzy zabezpieczenia:

- zapis kasuje ją PO commicie: zdarzenia sesji widzą ORM, DML i ``text()`` na
  tabelach polityki, więc nowa trasa nie musi o tym pamiętać, a odebranie
  uprawnienia działa od następnego żądania;
- odczyt zaczęty przed takim commitem nie trafia do bufora (``_generation``);
- po ``_CACHE_TTL_SECONDS`` czytamy od nowa: to siatka na to, czego zdarzenia
  tego procesu nie widzą (drugi kontener przy rolling update, skrypt, DDL ze startu).

Rola i nadpisania liczą się dla konta z jego wiersza ``users``, czytanego przy
każdym żądaniu, więc zmiana ról osoby bufora nie dotyczy.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NamedTuple

from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import ORMExecuteState, Session

from app.core.cache import cache_single_flight
from app.models.app_setting import AppSetting
from app.models.section_permission import (
    RbacPolicyState,
    RoleActionPermission,
    RoleSectionPermission,
    UserActionOverride,
    UserSectionOverride,
)

_CACHE_TTL_SECONDS = 30.0
_SINGLE_FLIGHT_KEY = "rbac_policy_snapshot"
# Lustro `notification_role_mutes.SETTING_KEY`: tamten moduł importuje modele
# powiadomień, a te zdarzenia muszą być zarejestrowane przy każdym imporcie.
_ROLE_MUTES_KEY = "notification_role_mutes"
_WRITES_KEY = "nexus_policy_writes"

_POLICY_MODELS = (
    RbacPolicyState,
    RoleSectionPermission,
    UserSectionOverride,
    RoleActionPermission,
    UserActionOverride,
)
_POLICY_TABLES = frozenset(model.__tablename__ for model in _POLICY_MODELS)

_clock = time.monotonic


class RoleSectionRow(NamedTuple):
    role: str
    section: str
    access: str


class UserSectionRow(NamedTuple):
    user_id: int
    section: str
    access: str


class RoleActionRow(NamedTuple):
    role: str
    action: str
    access: str


class UserActionRow(NamedTuple):
    user_id: int
    action: str
    access: str


@dataclass(frozen=True)
class PolicySnapshot:
    section_role_rows: tuple[RoleSectionRow, ...]
    section_overrides: Mapping[int, tuple[UserSectionRow, ...]]
    action_role_rows: tuple[RoleActionRow, ...]
    action_overrides: Mapping[int, tuple[UserActionRow, ...]]
    role_mutes: Mapping[str, Any]


_snapshot: PolicySnapshot | None = None
_expires_at = 0.0
_generation = 0


def invalidate_policy_cache() -> None:
    """Skasuj migawkę. Wołać po commicie, bo inaczej odczyt wstawi stare wiersze."""

    global _snapshot, _generation
    _snapshot = None
    _generation += 1


def _fresh_snapshot() -> PolicySnapshot | None:
    if _snapshot is not None and _clock() < _expires_at:
        return _snapshot
    return None


def _group_by_user(rows: list[Any]) -> dict[int, tuple[Any, ...]]:
    grouped: dict[int, list[Any]] = {}
    for row in rows:
        grouped.setdefault(row.user_id, []).append(row)
    return {user_id: tuple(items) for user_id, items in grouped.items()}


async def _load_snapshot(db: AsyncSession) -> PolicySnapshot:
    # Kolumny zamiast encji: encja już załadowana w tej sesji zachowałaby stare
    # wartości, a migawka idzie do wszystkich żądań. Komplet tabel, nie wiersze
    # kont z bieżącego żądania: to kilkaset małych krotek.
    from app.services.notification_role_mutes import normalise

    section_role_rows = await db.execute(
        select(
            RoleSectionPermission.role,
            RoleSectionPermission.section,
            RoleSectionPermission.access,
        )
    )
    section_override_rows = await db.execute(
        select(
            UserSectionOverride.user_id,
            UserSectionOverride.section,
            UserSectionOverride.access,
        )
    )
    action_role_rows = await db.execute(
        select(
            RoleActionPermission.role,
            RoleActionPermission.action,
            RoleActionPermission.access,
        )
    )
    action_override_rows = await db.execute(
        select(
            UserActionOverride.user_id,
            UserActionOverride.action,
            UserActionOverride.access,
        )
    )
    role_mutes = await db.execute(
        select(AppSetting.value).where(AppSetting.key == _ROLE_MUTES_KEY)
    )
    return PolicySnapshot(
        section_role_rows=tuple(
            RoleSectionRow(*row) for row in section_role_rows.all()
        ),
        section_overrides=_group_by_user(
            [UserSectionRow(*row) for row in section_override_rows.all()]
        ),
        action_role_rows=tuple(RoleActionRow(*row) for row in action_role_rows.all()),
        action_overrides=_group_by_user(
            [UserActionRow(*row) for row in action_override_rows.all()]
        ),
        role_mutes=normalise(role_mutes.scalar_one_or_none()),
    )


async def policy_snapshot(db: AsyncSession) -> PolicySnapshot | None:
    """Migawka polityki albo ``None``, gdy wołający ma czytać przez własną sesję.

    ``None`` dostaje sesja z niezatwierdzonym zapisem polityki: tylko ona widzi
    własne wiersze i nie wolno ich pokazać innym, zanim commit się uda.
    """

    if _CACHE_TTL_SECONDS <= 0 or db.info.get(_WRITES_KEY):
        return None
    snapshot = _fresh_snapshot()
    if snapshot is not None:
        return snapshot
    # Bez `db=`: oddanie połączenia to commit, a ten zwolniłby blokady `FOR UPDATE`,
    # które wołający mógł już wziąć. Wykonawca ma własne połączenie sesji.
    async with cache_single_flight(_SINGLE_FLIGHT_KEY):
        snapshot = _fresh_snapshot()
        if snapshot is not None:
            return snapshot
        generation = _generation
        started_at = _clock()
        snapshot = await _load_snapshot(db)
        if generation == _generation:
            _store(snapshot, started_at + _CACHE_TTL_SECONDS)
        return snapshot


def _store(snapshot: PolicySnapshot, expires_at: float) -> None:
    global _snapshot, _expires_at
    _snapshot = snapshot
    _expires_at = expires_at


# ── Kasowanie po zapisie ────────────────────────────────────────────────────


def _instance_touches_policy(instance: object) -> bool:
    if isinstance(instance, _POLICY_MODELS):
        return True
    return isinstance(instance, AppSetting) and instance.key == _ROLE_MUTES_KEY


def _statement_touches_policy(statement: Any) -> bool:
    table = getattr(statement, "table", None)
    if table is not None:
        return table.name in _POLICY_TABLES
    sql = getattr(statement, "text", None)
    if sql is None:
        return False
    return _ROLE_MUTES_KEY in sql or any(name in sql for name in _POLICY_TABLES)


@event.listens_for(Session, "after_flush")
def _mark_flushed_policy_writes(session: Session, _flush_context: Any) -> None:
    for pending in (session.new, session.dirty, session.deleted):
        if any(_instance_touches_policy(instance) for instance in pending):
            session.info[_WRITES_KEY] = True
            return


@event.listens_for(Session, "do_orm_execute")
def _mark_policy_statements(orm_execute_state: ORMExecuteState) -> None:
    if not orm_execute_state.is_select and _statement_touches_policy(
        orm_execute_state.statement
    ):
        orm_execute_state.session.info[_WRITES_KEY] = True


@event.listens_for(Session, "after_commit")
def _invalidate_after_commit(session: Session) -> None:
    # `after_commit` odpala się także przy zwolnieniu SAVEPOINT-u, a wtedy zapis
    # nie jest jeszcze widoczny dla innych.
    if session.in_nested_transaction():
        return
    if session.info.pop(_WRITES_KEY, None):
        invalidate_policy_cache()


@event.listens_for(Session, "after_transaction_end")
def _clear_policy_write_marker(session: Session, transaction: Any) -> None:
    # Wycofana transakcja niczego nie zmieniła, więc migawka zostaje.
    if transaction.parent is None:
        session.info.pop(_WRITES_KEY, None)
