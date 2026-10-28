"""Nowości do przeklikania — rejestr nowych funkcji NEXUSA (decyzja Artura 28.10.2026).

Ludzie nie czytali artefaktów „co nowego” (30 dni do 27.10: 478 dymków Jarvisa
u 46 osób, 1 otwarty przewodnik). Nowość pokazuje się więc kropką na tym
przycisku, którego dotyczy, i zalicza się z pracy: przeklikaniem po prawdziwym
ekranie albo pierwszym użyciem funkcji. Samo „przeczytałem” nie istnieje.

Trzy poziomy (``tier``):

- ``dot`` — drobiazg: kropka na elemencie, znika po pierwszym kliknięciu;
- ``tour`` — nowa funkcja: kropka + karta „Przeklikaj” z krokami po kotwicach
  ``data-tour`` (krok przechodzi po kliknięciu prawdziwego elementu);
- ``process`` — zmiana procesu: okno przy pierwszym wejściu na ekran
  ``path_prefix``, odłożyć można raz, do następnego ranka.

Wpis dopisuje PR, który wdraża nowość. Kotwice kroków muszą istnieć we
froncie jako ``data-tour`` — pilnuje tego test frontu
(``lib/novelties/__tests__/novelty-anchors.test.ts``), który czyta ten plik
ścieżką względną, jak przewodniki ekranów.
"""

from __future__ import annotations

import json
from collections.abc import Collection
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.user import UserRole
from app.services import permission_catalog

NOVELTIES_PATH = Path(__file__).resolve().parent / "novelties.json"

_ANCHOR = r"^[a-z0-9][a-z0-9_.-]{1,59}$"
_NOVELTY_ID = r"^[a-z0-9][a-z0-9-]{2,59}$"

NoveltyTier = Literal["dot", "tour", "process"]

#: Domyślnie nowość żyje 45 dni od wdrożenia — potem znika z kropek i listy,
#: a panel „kto już umie” pokazuje ją jeszcze do 90 dni.
DEFAULT_ACTIVE_DAYS = 45
PANEL_DAYS = 90


class NoveltyAudience(BaseModel):
    """Kogo nowość dotyczy. Pusta lista ról i uprawnień = wszyscy."""

    model_config = ConfigDict(extra="forbid")

    roles: list[str] = Field(default_factory=list)
    #: Wystarczy jedno — przycisk pokazywany posiadaczom uprawnienia opisujemy
    #: uprawnieniem, nie listą ról.
    permissions: list[str] = Field(default_factory=list)

    @field_validator("roles")
    @classmethod
    def _known_roles(cls, value: list[str]) -> list[str]:
        known = {role.value for role in UserRole}
        unknown = [role for role in value if role not in known]
        if unknown:
            raise ValueError(f"Nieznana rola w nowości: {unknown}")
        return value

    @field_validator("permissions")
    @classmethod
    def _known_permissions(cls, value: list[str]) -> list[str]:
        unknown = [key for key in value if key not in permission_catalog.BY_KEY]
        if unknown:
            raise ValueError(f"Nieznane uprawnienie w nowości: {unknown}")
        return value


class TourStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor: str = Field(pattern=_ANCHOR)
    text: str = Field(min_length=1, max_length=90)
    hint: str = Field(min_length=1, max_length=160)
    #: Krok, którego nie wolno wykonać naprawdę (np. „Zapisz” zakończenia
    #: kontraktu): przechodzi przyciskiem „Rozumiem”, nie kliknięciem kotwicy.
    ack: bool = False


class Novelty(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_NOVELTY_ID)
    title: str = Field(min_length=1, max_length=80)
    why: str = Field(min_length=1, max_length=200)
    tier: NoveltyTier
    shipped_on: date
    pr: Optional[int] = None
    audience: NoveltyAudience = Field(default_factory=NoveltyAudience)
    #: Gdzie jest nowość, słowami użytkownika („Rekrutacja → Kandydaci do dodania”).
    where: str = Field(min_length=1, max_length=80)
    #: Ekran, na który prowadzi pozycja listy „Nowości”.
    href: str = Field(pattern=r"^/[a-z0-9/_-]*$", max_length=80)
    #: Kotwica ``data-tour``, przy której stoi kropka.
    dot_anchor: str = Field(pattern=_ANCHOR)
    #: Kliknięcie tej kotwicy poza przeklikaniem = „użyte w pracy”.
    used_anchor: Optional[str] = Field(default=None, pattern=_ANCHOR)
    #: Ekran, przy którego otwarciu pokazuje się okno zmiany procesu.
    path_prefix: Optional[str] = Field(default=None, pattern=r"^/[a-z0-9/_-]*$")
    steps: list[TourStep] = Field(default_factory=list, max_length=6)
    active_days: int = Field(default=DEFAULT_ACTIVE_DAYS, ge=7, le=90)

    @model_validator(mode="after")
    def _tier_shape(self) -> "Novelty":
        if self.tier == "dot" and self.steps:
            raise ValueError(f"{self.id}: drobiazg nie ma kroków przeklikania")
        if self.tier != "dot" and len(self.steps) < 2:
            raise ValueError(f"{self.id}: przeklikanie potrzebuje co najmniej 2 kroków")
        if self.tier == "process" and not self.path_prefix:
            raise ValueError(f"{self.id}: zmiana procesu potrzebuje path_prefix ekranu")
        if self.tier != "process" and self.path_prefix:
            raise ValueError(
                f"{self.id}: path_prefix ma sens tylko przy zmianie procesu"
            )
        return self

    def active_on(self, day: date) -> bool:
        return (
            self.shipped_on <= day < self.shipped_on + timedelta(days=self.active_days)
        )

    def in_panel_on(self, day: date) -> bool:
        return self.shipped_on <= day < self.shipped_on + timedelta(days=PANEL_DAYS)


@lru_cache(maxsize=1)
def load_novelties() -> dict[str, Novelty]:
    """Nowości po id, w kolejności pliku. Zły plik = wyjątek przy starcie testów."""
    raw = json.loads(NOVELTIES_PATH.read_text(encoding="utf-8"))
    by_id: dict[str, Novelty] = {}
    for item in raw:
        novelty = Novelty.model_validate(item)
        if novelty.id in by_id:
            raise ValueError(f"Powtórzone id nowości: {novelty.id}")
        by_id[novelty.id] = novelty
    return by_id


def in_audience(
    novelty: Novelty, roles: Collection[str], permissions: Collection[str]
) -> bool:
    audience = novelty.audience
    if not audience.roles and not audience.permissions:
        return True
    if audience.roles and set(roles) & set(audience.roles):
        return True
    if audience.permissions and set(permissions) & set(audience.permissions):
        return True
    return False
