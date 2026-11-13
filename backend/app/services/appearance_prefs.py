"""Świat wyglądu per osoba (``users.appearance_prefs``).

Lista światów ma lustro we froncie (``frontend/src/lib/worlds/world-ids.ts``);
test ``tests/test_appearance_prefs.py`` porównuje obie strony. ``game`` to
dzisiejszy tryb gry, ``none`` — bez świata. Reguła
``docs/claude/ui/swiaty-wygladu.md``.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, field_validator

WORLD_IDS: tuple[str, ...] = (
    "none",
    "game",
    "arcade",
    "stadium",
    "space",
    "zen",
    "winter",
    "retro",
    "sakura",
    "latte",
    "lavender",
    "botanic",
    "marble",
    "sunset",
    "holo",
    "tulips",
    "pitstop",
    "rgb",
    "mountains",
    "blueprint",
)
_KNOWN = frozenset(WORLD_IDS)


def _check_world(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in _KNOWN:
        raise ValueError("Nieznany świat.")
    return value


class AppearancePrefs(BaseModel):
    """Zapisany świat. ``world = None`` = osoba jeszcze nic nie zapisała
    na koncie (front wtedy wysyła swój wybór z przeglądarki)."""

    world: Optional[str] = None
    # Świat sprzed sezonowego (Zima, Tulipany) — po końcu sezonu front wraca
    # do niego, zamiast zostawiać osobę bez świata.
    world_before_season: Optional[str] = None


class AppearancePrefsUpdate(BaseModel):
    world: Optional[str] = None
    world_before_season: Optional[str] = None

    _valid_world = field_validator("world", "world_before_season")(_check_world)


def effective_appearance(raw: Any) -> AppearancePrefs:
    """Zapis z bazy → model; nieznane albo popsute wartości odpadają po cichu,
    bo świat jest dodatkiem i nie może zablokować odczytu preferencji."""
    if not isinstance(raw, dict):
        return AppearancePrefs()
    world = raw.get("world")
    before = raw.get("world_before_season")
    return AppearancePrefs(
        world=world if world in _KNOWN else None,
        world_before_season=before if before in _KNOWN else None,
    )


def apply_appearance_update(
    current: AppearancePrefs, update: AppearancePrefsUpdate
) -> AppearancePrefs:
    changes = update.model_dump(exclude_unset=True)
    return current.model_copy(update=changes)
