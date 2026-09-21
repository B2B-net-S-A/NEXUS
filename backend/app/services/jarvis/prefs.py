"""Wygląd i zachowanie maskotki Jarvisa per osoba (``users.jarvis_prefs``).

Postaci to gotowe ilustracje (decyzja 21.09.2026) — lustro listy jest we
froncie (``frontend/src/components/jarvis/characters``); test kontraktowy
porównuje obie strony. Dwie postaci są ODBLOKOWYWANE wynikiem w Lidze
Mistrzów (zamrożone ``competition_winners``): serwer liczy ``unlocked`` przy
każdym odczycie i odrzuca zapis postaci, której ktoś nie odblokował.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.competition_winner import CompetitionWinner

JarvisCharacter = Literal[
    "robot",
    "owl",
    "cat",
    "ghost",
    "rocket",
    "star",
    "dragon",
    "astronaut",
    "robot_gold",
    "trophy",
]
BASE_CHARACTERS: tuple[str, ...] = (
    "robot",
    "owl",
    "cat",
    "ghost",
    "rocket",
    "star",
    "dragon",
    "astronaut",
)
# postać → warunek odblokowania (opis dla UI)
UNLOCKABLE_CHARACTERS: dict[str, str] = {
    "robot_gold": "Wygraj dowolny ranking Ligi Mistrzów (1. miejsce).",
    "trophy": "Stań na podium Ligi Mistrzów (miejsca 1–3).",
}
JarvisAccent = Literal[
    "primary", "violet", "blue", "green", "orange", "rose", "graphite"
]

DEFAULT_PREFS: dict[str, Any] = {
    "character": "robot",
    "name": "Jarvis",
    "accent": "primary",
    "enabled": True,
    "minimized": False,
    "sound": False,
    "daily_brief": True,
}


class JarvisPrefs(BaseModel):
    character: JarvisCharacter = "robot"
    name: str = Field(default="Jarvis", min_length=1, max_length=24)
    accent: JarvisAccent = "primary"
    enabled: bool = True
    minimized: bool = False
    sound: bool = False
    daily_brief: bool = True

    @field_validator("name")
    @classmethod
    def _clean_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("Imię asystenta nie może być puste")
        if any(ch in cleaned for ch in "<>{}[]`"):
            raise ValueError(
                "Imię asystenta może zawierać tylko litery, cyfry i spacje"
            )
        return cleaned


class JarvisPrefsUpdate(BaseModel):
    character: Optional[JarvisCharacter] = None
    name: Optional[str] = Field(default=None, min_length=1, max_length=24)
    accent: Optional[JarvisAccent] = None
    enabled: Optional[bool] = None
    minimized: Optional[bool] = None
    sound: Optional[bool] = None
    daily_brief: Optional[bool] = None


def effective_prefs(raw: Any) -> JarvisPrefs:
    """Zapisane preferencje nałożone na domyślne; śmieci w JSONB → domyślne."""
    merged = dict(DEFAULT_PREFS)
    if isinstance(raw, dict):
        merged.update({k: v for k, v in raw.items() if k in DEFAULT_PREFS})
    try:
        return JarvisPrefs(**merged)
    except ValueError:
        return JarvisPrefs()


async def unlocked_characters(db: AsyncSession, user_id: int) -> list[str]:
    best_rank = await db.scalar(
        select(func.min(CompetitionWinner.rank)).where(
            CompetitionWinner.user_id == user_id
        )
    )
    unlocked = list(BASE_CHARACTERS)
    if best_rank is not None and best_rank <= 3:
        unlocked.append("trophy")
    if best_rank == 1:
        unlocked.append("robot_gold")
    return unlocked


def apply_update(current: JarvisPrefs, update: JarvisPrefsUpdate) -> JarvisPrefs:
    data = current.model_dump()
    data.update(update.model_dump(exclude_unset=True, exclude_none=True))
    return JarvisPrefs(**data)
