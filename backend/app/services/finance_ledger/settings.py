"""Przełącznik modułu „Księgowość” (``app_settings['finance_accounting']``).

Moduł wchodzi na produkcję wyłączony, jak rozliczenia klientów: włącza go
administrator, kiedy Finanse zaczynają pracę w NEXUSIE zamiast w eBI24. Brak
wiersza albo wartość inna niż ``{"enabled": true}`` = wyłączony. Admin widzi
ekrany także przy wyłączonym module. Wyłączony program „Ludzi w NEXUSIE”
(``HR_PROGRAM_ENABLED``) zamyka moduł dla wszystkich, bo faktury przychodzą
z pętli KSeF tego programu.

Włączony moduł zapisuje też faktury dostawców z KSeF jako dokumenty wydatków
przy wyłączonym module „Zgody” (``hr/ksef/sync.py``) — inaczej dostawcy biura
nie trafiliby do kolejki kosztów.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.user import User, UserRole
from app.services.hr.program import program_enabled

SETTING_KEY = "finance_accounting"
MODULE_DISABLED_DETAIL = "Moduł „Księgowość” jest wyłączony."


def normalize(raw: object) -> dict[str, Any]:
    enabled = isinstance(raw, dict) and raw.get("enabled") is True
    return {"enabled": enabled}


async def load(db: AsyncSession) -> dict[str, Any]:
    if not program_enabled():
        return normalize(None)
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    return normalize(raw)


async def is_enabled(db: AsyncSession) -> bool:
    return bool((await load(db))["enabled"])


def open_for(user: User, enabled: bool) -> bool:
    """Czy ekrany modułu działają dla tej osoby (przy włączonym programie
    admin widzi je zawsze)."""

    if not program_enabled():
        return False
    return enabled or user.has_role(UserRole.admin)


async def set_enabled(
    db: AsyncSession, enabled: bool, *, actor: User
) -> dict[str, Any]:
    """Zapis przełącznika (bez commita)."""

    value = {"enabled": bool(enabled)}
    statement = insert(AppSetting).values(
        key=SETTING_KEY, value=value, updated_by=actor.id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor.id},
        )
    )
    return value
