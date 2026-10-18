"""Przełącznik modułu faktur do klientów (``app_settings['client_invoicing']``).

Moduł wchodzi na produkcję wyłączony (decyzja E8, 17.10.2026): włącza go
administrator, gdy Finanse potwierdzą, że faktury sprzedażowe są w KSeF.
Brak wiersza albo wartość inna niż ``{"enabled": true}`` = wyłączony.
Admin widzi ekrany także przy wyłączonym module (przygotowanie, sprawdzenie
pozycji „do faktury”); pętla KSeF i uznania z wyciągu działają tylko przy
włączonym.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.user import User, UserRole

SETTING_KEY = "client_invoicing"
MODULE_DISABLED_DETAIL = "Moduł faktur do klientów jest wyłączony."


def normalize(raw: object) -> dict[str, Any]:
    enabled = isinstance(raw, dict) and raw.get("enabled") is True
    return {"enabled": enabled}


async def load(db: AsyncSession) -> dict[str, Any]:
    raw = await db.scalar(select(AppSetting.value).where(AppSetting.key == SETTING_KEY))
    return normalize(raw)


async def is_enabled(db: AsyncSession) -> bool:
    return bool((await load(db))["enabled"])


def open_for(user: User, enabled: bool) -> bool:
    """Czy ekrany modułu działają dla tej osoby (admin widzi je zawsze)."""

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
