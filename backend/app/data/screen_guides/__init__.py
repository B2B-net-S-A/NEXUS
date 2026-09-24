"""Przewodniki ekranów Jarvisa — „co tu robię i jak”.

Jedno źródło treści (``guides.json``) dla dwóch odbiorców:

- **front** pobiera je trasą ``GET /api/help/screens`` i pokazuje dymek przy
  pierwszej wizycie na ekranie oraz kartę przewodnika w panelu Jarvisa — bez
  wywołania modelu;
- **Jarvis** czyta je narzędziem ``get_screen_guide``, gdy ktoś pyta
  „jak…/gdzie…/co tu…”, i podświetla elementy z listy ``anchors``.

Obrazy Dockera frontu i backendu nie widzą swoich katalogów, więc plik żyje
w backendzie, a front czyta go przez API (testy vitest czytają go ścieżką
względną, jak instrukcję zamówień).

Przewodnik opisuje ZACHOWANIE EKRANU, więc psuje się, gdy ktoś zmieni ekran —
nie gdy zmieni się proces. ``sources`` każdego wpisu to pliki, których zmiana
każe przejrzeć przewodnik; odciski z ostatniego przeglądu leżą w
``stamps/<klucz ekranu>.json`` (osobny plik na ekran, patrz
``app/data/review_stamps.py``), a pilnuje ich
``tests/test_screen_guides_freshness.py`` (ten sam mechanizm co instrukcja
zamówień). Po przeglądzie:

    cd backend && python3 scripts/stamp_screen_guides.py
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

_THIS_DIR = Path(__file__).resolve().parent
GUIDES_PATH = _THIS_DIR / "guides.json"
#: Katalog główny repozytorium — ``sources`` są względne wobec niego.
REPO_ROOT = _THIS_DIR.parents[3]

#: Ekrany z przewodnikiem (decyzja 23.09.2026: 12 najważniejszych). Lustro
#: unii ``ScreenKey`` we froncie (``lib/help/screen-key.ts``) — pilnuje test.
SCREEN_KEYS: tuple[str, ...] = (
    "jobs.list",
    "jobs.board",
    "jobs.proposals",
    "jobs.person",
    "job.champion",
    "candidates.list",
    "candidate.profile",
    "calendar",
    "client.orders",
    "contracts.order_mail",
    "contracts.b2b_generator",
    "finance",
)

_ANCHOR_ID = r"^[a-z0-9][a-z0-9_.-]{1,59}$"
_SCREEN_KEY = r"^[a-z0-9_.]{1,60}$"


class AnchorRequires(BaseModel):
    """Kto widzi element na ekranie — kotwica nie może wskazywać przycisku,
    którego ta osoba nie ma."""

    model_config = ConfigDict(extra="forbid")

    roles: list[str] = Field(default_factory=list)
    section: Optional[str] = None


class GuideAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=_ANCHOR_ID)
    label: str = Field(min_length=1, max_length=60)
    describe: str = Field(min_length=1, max_length=200)
    requires: Optional[AnchorRequires] = None


class GuideTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    q: str = Field(min_length=1, max_length=120)
    a: str = Field(min_length=1, max_length=350)
    anchor: Optional[str] = Field(default=None, pattern=_ANCHOR_ID)


class ScreenGuide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(pattern=_SCREEN_KEY)
    title: str = Field(min_length=1, max_length=60)
    #: Sekcja produktu, bez której ekranu nie ma — przewodnika też nie ma.
    section: Optional[str] = None
    #: Kto tu głównie pracuje (informacja dla modelu, nie bramka).
    roles: list[str] = Field(default_factory=list)
    what: str = Field(min_length=1, max_length=240)
    tasks: list[GuideTask] = Field(min_length=3, max_length=5)
    pitfalls: list[str] = Field(default_factory=list, max_length=4)
    anchors: list[GuideAnchor] = Field(min_length=2, max_length=6)
    help_slug: Optional[str] = None
    sources: list[str] = Field(min_length=1, max_length=3)


@lru_cache(maxsize=1)
def load_guides() -> dict[str, ScreenGuide]:
    """Przewodniki po kluczu ekranu. Zły plik = wyjątek przy starcie testów."""
    raw = json.loads(GUIDES_PATH.read_text(encoding="utf-8"))
    guides = [ScreenGuide.model_validate(item) for item in raw]
    by_key: dict[str, ScreenGuide] = {}
    for guide in guides:
        if guide.key in by_key:
            raise ValueError(f"Powtórzony klucz przewodnika: {guide.key}")
        by_key[guide.key] = guide
    return by_key


def _anchor_visible(
    anchor: GuideAnchor, roles: set[str], sections: dict[str, int]
) -> bool:
    requires = anchor.requires
    if requires is None:
        return True
    if requires.roles and not (roles & set(requires.roles)):
        return False
    if requires.section and sections.get(requires.section, 0) < 1:
        return False
    return True


def guide_for_user(
    guide: ScreenGuide, roles: set[str], sections: dict[str, int]
) -> Optional[dict[str, Any]]:
    """Przewodnik w kształcie dla odbiorcy — bez ``sources``, z kotwicami,
    które ta osoba naprawdę widzi. ``None``: ekranu nie ma w jej menu."""
    if guide.section and sections.get(guide.section, 0) < 1:
        return None
    visible = [a for a in guide.anchors if _anchor_visible(a, roles, sections)]
    visible_ids = {a.id for a in visible}
    data = guide.model_dump(exclude={"sources"})
    data["anchors"] = [a.model_dump() for a in visible]
    data["tasks"] = [
        {**t.model_dump(), "anchor": t.anchor if t.anchor in visible_ids else None}
        for t in guide.tasks
    ]
    return data
