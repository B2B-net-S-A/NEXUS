"""Wyłącznik ``app_settings['consultant_portal']``: off, pilot, all (wzór ``b2b_esign``).

Brak wiersza = ``off``: publiczne trasy odpowiadają 404, a do ludzi spoza firmy nic
nie wychodzi. W stanach ``pilot`` i ``all`` panel otwiera się wyłącznie kontraktom
z aktywną aktywacją (``cp_activations``), bo panel powstaje ręcznie po podpisaniu umowy.

``pilot`` działa bez modułu ``back_office``: to test na pojedynczych osobach, zanim
tablica ruszy. ``all`` wymaga modułu, bo bez niego dokumenty nie mają odbiorcy, i dopiero
w nim czytnik poczty zakłada karty nieznanym nadawcom.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.consultant_panel import CpActivation
from app.models.consultant_portal import CpSession
from app.services.hr import modules as hr_modules
from app.services.consultant_portal_schema import PORTAL_SETTING, STATES


@dataclass(frozen=True)
class PortalSettings:
    state: str = "off"
    activated_contract_ids: frozenset[int] = frozenset()

    @property
    def is_on(self) -> bool:
        return self.state in ("pilot", "all")

    def open_for(self, contract_id: int) -> bool:
        return self.is_on and contract_id in self.activated_contract_ids

    def as_dict(self) -> dict[str, Any]:
        return {"state": self.state}


def parse(raw: Any) -> PortalSettings:
    if not isinstance(raw, dict):
        return PortalSettings()
    state = raw.get("state")
    if state not in STATES:
        # Nieczytelny wpis zamyka portal: to wyłącznik wysyłki do ludzi z zewnątrz.
        return PortalSettings()
    return PortalSettings(state=state)


async def load(db: AsyncSession) -> PortalSettings:
    """Stan portalu z listą aktywowanych kontraktów."""

    state = parse(
        await db.scalar(
            select(AppSetting.value).where(AppSetting.key == PORTAL_SETTING)
        )
    )
    if not state.is_on or not hr_modules.program_enabled():
        return PortalSettings()
    if state.state == "all" and not (await hr_modules.load_modules(db)).get(
        hr_modules.HrModule.back_office
    ):
        return PortalSettings()
    activated = await db.scalars(
        select(CpActivation.contract_id).where(CpActivation.deactivated_at.is_(None))
    )
    return PortalSettings(
        state=state.state, activated_contract_ids=frozenset(activated.all())
    )


async def load_raw_state(db: AsyncSession) -> str:
    """Ustawienie, a nie skutek: ekran wyłącznika pokazuje to, co wybrał admin."""

    return parse(
        await db.scalar(
            select(AppSetting.value).where(AppSetting.key == PORTAL_SETTING)
        )
    ).state


async def save(db: AsyncSession, *, state: str) -> PortalSettings:
    value = PortalSettings(state=state if state in STATES else "off").as_dict()
    await db.execute(
        insert(AppSetting)
        .values(key=PORTAL_SETTING, value=value)
        .on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value})
    )
    if value["state"] == "off":
        # Wyłącznik awaryjny: ponowne włączenie nie ożywia sesji sprzed wyłączenia.
        await db.execute(delete(CpSession))
    return parse(value)
