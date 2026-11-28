"""Włącznik wejścia trenera z rynku: ``app_settings['market_trainer_portal']``.

Brak wiersza albo nieczytelny wpis = wyłączony (to wyłącznik wysyłki do ludzi
z zewnątrz). Działa tylko przy włączonym programie „Ludzie w NEXUSIE”, bo szkolenia
są jego modułem. Wyłączenie kasuje sesje trenerów: ponowne włączenie ich nie ożywia.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.website_intake import MtPortalSession
from app.services.hr import modules as hr_modules

KEY = "market_trainer_portal"


def parse(raw: Any) -> bool:
    return isinstance(raw, dict) and raw.get("enabled") is True


async def is_enabled(db: AsyncSession) -> bool:
    if not hr_modules.program_enabled():
        return False
    return parse(await db.scalar(select(AppSetting.value).where(AppSetting.key == KEY)))


async def save(db: AsyncSession, *, enabled: bool) -> bool:
    value = {"enabled": bool(enabled)}
    await db.execute(
        insert(AppSetting)
        .values(key=KEY, value=value)
        .on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value})
    )
    if not enabled:
        await db.execute(delete(MtPortalSession))
    return bool(enabled)
