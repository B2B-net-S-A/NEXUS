"""Przełącznik „Podpis umów w NEXUSIE” (``app_settings['b2b_esign']``).

Droga zwykła zostaje zawsze. Ta działa obok niej w trzech stanach (makieta 8):
``off`` (po wdrożeniu), ``pilot`` (tylko wybrane konta wysyłają) i ``all``.
Za B2B Network podpisuje osoba z listy ``company_signer_ids`` — imienny
reprezentant (pieczęć firmy nie zastępuje podpisu osoby przy przeniesieniu
praw autorskich). Brak wpisu = wyłączone.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.user import User

SETTINGS_KEY = "b2b_esign"
Mode = Literal["off", "pilot", "all"]
_MODES: tuple[str, ...] = ("off", "pilot", "all")


@dataclass(frozen=True)
class EsignSettings:
    mode: Mode = "off"
    pilot_user_ids: frozenset[int] = frozenset()
    company_signer_ids: tuple[int, ...] = ()

    def can_send(self, user: User) -> bool:
        """Czy to konto widzi „W NEXUSIE” w oknie wysyłki."""
        if self.mode == "all":
            return True
        return self.mode == "pilot" and user.id in self.pilot_user_ids

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "pilot_user_ids": sorted(self.pilot_user_ids),
            "company_signer_ids": list(self.company_signer_ids),
        }


def _ids(raw: Any) -> list[int]:
    if not isinstance(raw, list):
        return []
    return [value for value in raw if isinstance(value, int) and value > 0]


def parse(raw: Any) -> EsignSettings:
    """Wpis z bazy → ustawienia; wszystko nierozpoznane = wyłączone."""
    if not isinstance(raw, dict):
        return EsignSettings()
    mode = raw.get("mode")
    return EsignSettings(
        mode=mode if mode in _MODES else "off",
        pilot_user_ids=frozenset(_ids(raw.get("pilot_user_ids"))),
        # Kolejność zostaje — pierwsza osoba jest domyślna w oknie wysyłki.
        company_signer_ids=tuple(dict.fromkeys(_ids(raw.get("company_signer_ids")))),
    )


async def load(db: AsyncSession) -> EsignSettings:
    raw = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == SETTINGS_KEY)
    )
    return parse(raw)


async def save(db: AsyncSession, value: EsignSettings, *, actor_id: int) -> None:
    statement = insert(AppSetting).values(
        key=SETTINGS_KEY, value=value.as_dict(), updated_by=actor_id
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": statement.excluded.value, "updated_by": actor_id},
        )
    )
