"""Wyłącznik ``app_settings['consultant_portal']``: off, pilot, all (wzór ``b2b_esign``).

Brak wiersza = ``off``: publiczne trasy odpowiadają 404, a do ludzi spoza firmy nic
nie wychodzi. Pilot obejmuje wyłącznie wskazane kontrakty.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.consultant_portal import CpSession
from app.services.hr import modules as hr_modules
from app.services.consultant_portal_schema import PORTAL_SETTING, STATES


@dataclass(frozen=True)
class PortalSettings:
    state: str = "off"
    pilot_contract_ids: frozenset[int] = frozenset()

    @property
    def is_on(self) -> bool:
        return self.state in ("pilot", "all")

    def open_for(self, contract_id: int) -> bool:
        if self.state == "all":
            return True
        return self.state == "pilot" and contract_id in self.pilot_contract_ids

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "pilot_contract_ids": sorted(self.pilot_contract_ids),
        }


def _ids(raw: Any) -> frozenset[int]:
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(
        value
        for value in raw
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
    )


def parse(raw: Any) -> PortalSettings:
    if not isinstance(raw, dict):
        return PortalSettings()
    state = raw.get("state")
    if state not in STATES:
        # Nieczytelny wpis zamyka portal: to wyłącznik wysyłki do ludzi z zewnątrz.
        return PortalSettings()
    return PortalSettings(
        state=state, pilot_contract_ids=_ids(raw.get("pilot_contract_ids"))
    )


async def load(db: AsyncSession) -> PortalSettings:
    """Stan portalu. Wyłączony moduł ``back_office`` zamyka też portal, bo wycofanie
    to wyłączenie modułu, a bez niego zgłoszenia i dokumenty nie mają odbiorcy."""

    state = parse(
        await db.scalar(
            select(AppSetting.value).where(AppSetting.key == PORTAL_SETTING)
        )
    )
    if state.is_on and not (
        hr_modules.program_enabled()
        and (await hr_modules.load_modules(db)).get(hr_modules.HrModule.back_office)
    ):
        return PortalSettings()
    return state


async def save(
    db: AsyncSession, *, state: str, pilot_contract_ids: Iterable[int]
) -> PortalSettings:
    value = PortalSettings(
        state=state if state in STATES else "off",
        pilot_contract_ids=frozenset(pilot_contract_ids),
    ).as_dict()
    await db.execute(
        insert(AppSetting)
        .values(key=PORTAL_SETTING, value=value)
        .on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value})
    )
    if value["state"] == "off":
        # Wyłącznik awaryjny: ponowne włączenie nie ożywia sesji sprzed wyłączenia.
        await db.execute(delete(CpSession))
    return parse(value)
