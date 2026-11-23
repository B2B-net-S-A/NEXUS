"""„Nowy wzór umowy podpięty” (``app_settings['b2b_mass_send']``, E5b).

Decyzja Artura 22.11.2026: nowa umowa B2B (przeniesienie autorskich praw
majątkowych) jest jeszcze w przygotowaniu, więc masowa wysyłka powstaje na
obecnym wzorze Generatora, a do ludzi nie wychodzi nic, dopóki admin jawnie
nie oznaczy nowego wzoru jako podpiętego. Brak wpisu albo wpis nierozpoznany
= zablokowane. Podgląd i próba bez wysyłki działają zawsze.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

SETTINGS_KEY = "b2b_mass_send"


@dataclass(frozen=True)
class MassSendSettings:
    template_ready: bool = False
    marked_by: Optional[int] = None
    marked_at: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "template_ready": self.template_ready,
            "marked_by": self.marked_by,
            "marked_at": self.marked_at,
        }


def parse(raw: Any) -> MassSendSettings:
    """Tylko jawne ``True`` odblokowuje wysyłkę."""
    if not isinstance(raw, dict):
        return MassSendSettings()
    marked_by = raw.get("marked_by")
    marked_at = raw.get("marked_at")
    return MassSendSettings(
        template_ready=raw.get("template_ready") is True,
        marked_by=marked_by if isinstance(marked_by, int) else None,
        marked_at=marked_at if isinstance(marked_at, str) else None,
    )


async def load(db: AsyncSession) -> MassSendSettings:
    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == SETTINGS_KEY)
    )
    return parse(raw)


async def save(
    db: AsyncSession, *, template_ready: bool, actor_id: int, now: datetime
) -> MassSendSettings:
    value = MassSendSettings(
        template_ready=template_ready, marked_by=actor_id, marked_at=now.isoformat()
    )
    statement = insert(AppSetting).values(
        key=SETTINGS_KEY, value=value.as_dict(), updated_by=actor_id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor_id},
        )
    )
    return value
