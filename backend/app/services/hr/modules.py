"""Przełączniki modułów „Ludzi w NEXUSIE” (``app_settings['hr_modules']``).

Moduły wchodzą na produkcję wyłączone i są włączane przy przełączeniu
z Compassa, bez wdrożenia (decyzja Artura 16.10.2026: jeden PR, potem
przełączenia modułami). Brak wiersza albo nieznany klucz = wyłączony.
Przy włączonym programie admin widzi ekrany także przy wyłączonym module
(przygotowanie importu); wyłączony program (``HR_PROGRAM_ENABLED``) zamyka
wszystkie moduły dla wszystkich, także admina (``hr.program``).
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.user import User, UserRole
from app.services.hr.program import program_enabled
from app.services.hr_foundation_schema import HR_MODULE_KEYS, HR_MODULES_SETTING


class HrModule(StrEnum):
    """Klucze przełączników (te same wartości co ``HR_MODULE_KEYS``)."""

    people = "people"
    leave = "leave"
    time = "time"
    payroll = "payroll"
    lifecycle = "lifecycle"
    care = "care"
    cases = "cases"
    equipment = "equipment"
    #: Rozliczenia zespołu (etap 4): faktury z KSeF, potwierdzenia godzin,
    #: płatności i eksport do Symfonii — domyślnie wyłączone.
    settlements = "settlements"
    #: Zgody na wydatki i premie poza umową (0483) — domyślnie wyłączone.
    approvals = "approvals"


def normalize(raw: object) -> dict[str, bool]:
    """Komplet kluczy; wszystko, co nie jest ``True``, to wyłączony moduł."""

    source = raw if isinstance(raw, Mapping) else {}
    return {key: source.get(key) is True for key in HR_MODULE_KEYS}


async def load_modules(db: AsyncSession) -> dict[str, bool]:
    if not program_enabled():
        return normalize(None)
    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == HR_MODULES_SETTING)
    )
    return normalize(raw)


def module_open_for(user: User, modules: Mapping[str, bool], key: str) -> bool:
    """Czy moduł działa dla tej osoby (przy włączonym programie admin widzi
    ekrany zawsze)."""

    if not program_enabled():
        return False
    return bool(modules.get(key)) or user.has_role(UserRole.admin)


class UnknownModuleError(ValueError):
    pass


async def set_modules(
    db: AsyncSession, changes: Mapping[str, bool], *, actor: User
) -> dict[str, bool]:
    """Zmienia wybrane przełączniki; zwraca stan po zmianie (bez commita)."""

    unknown = sorted(set(changes) - set(HR_MODULE_KEYS))
    if unknown:
        raise UnknownModuleError(", ".join(unknown))
    current = await load_modules(db)
    updated = {**current, **{key: bool(value) for key, value in changes.items()}}
    statement = insert(AppSetting).values(
        key=HR_MODULES_SETTING, value=updated, updated_by=actor.id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor.id},
        )
    )
    return updated
