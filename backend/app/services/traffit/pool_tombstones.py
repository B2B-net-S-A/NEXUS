"""Nagrobki pul talentów z Traffita usuniętych w NEXUSIE (runda 10, R10-N11-7).

Faza `talents` przegląda co noc cały `/talents/` i robi upsert po
`(external_source, external_id)`, więc usunięta w NEXUSIE pula wracała
następnej nocy (pusta, ale z nazwą). Nagrobek to numer rekordu Traffita
w `app_settings` — bez nazw i danych osób.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

TOMBSTONES_KEY = "traffit_talent_pool_tombstones"


async def load_deleted_traffit_pools(db: AsyncSession) -> set[str]:
    setting = await db.get(AppSetting, TOMBSTONES_KEY)
    raw = (setting.value or {}).get("external_ids", []) if setting else []
    return {str(v) for v in raw if v is not None}


async def add_deleted_traffit_pool(db: AsyncSession, external_id: str) -> None:
    setting = await db.get(AppSetting, TOMBSTONES_KEY, with_for_update=True)
    if setting is None:
        db.add(AppSetting(key=TOMBSTONES_KEY, value={"external_ids": [external_id]}))
        return
    ids = [str(v) for v in (setting.value or {}).get("external_ids", [])]
    if external_id not in ids:
        ids.append(external_id)
    # Nowy słownik — JSONB bez MutableDict nie widzi zmian w miejscu.
    setting.value = {**(setting.value or {}), "external_ids": ids}
