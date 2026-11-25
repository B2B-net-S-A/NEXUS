"""Strona 1 zawsze na jednej kartce A4 — skracanie krokami (reguła z makiety, 20.11.2026).

Najpierw pismo strony 1 od 11 pt w dół do 9 pt (do 11 pt: Artur 25.11.2026 —
mało treści ma wypełnić kartkę większym pismem, nie dziurami), potem najwięcej
pozycji w kategorii umiejętności (10 → 4, nadmiar jako „+N”, pełna lista na
str. 2), na końcu pismo do 8 pt. Pomiar robi WeasyPrint: sama strona 1 mieści się,
gdy jej układ ma jedną stronę. Wolne miejsce, które zostanie: połowa w środek
sekcji (odstępy zdań, wierszy, osi), reszta równo między sekcje.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any, Optional

from app.services.cv_new_layout.context import Ctx
from app.services.cv_new_layout.render import (
    LayoutSettings,
    build_html,
    html_to_document,
)
from app.services.cv_new_layout.styles import PAGE1_HEIGHT

logger = logging.getLogger(__name__)

PX_TO_MM = 25.4 / 96
# pismo poniżej 10 pt to skrócenie (komunikat dla rekrutera); 10–11 pt to wypełnianie kartki
BASE_FONT_PT = 10.0

STEPS: tuple[LayoutSettings, ...] = tuple(
    LayoutSettings(font_pt=fs, skill_cap=cap)
    for fs, cap in (
        (11.0, None),
        (10.8, None),
        (10.6, None),
        (10.4, None),
        (10.2, None),
        (10.0, None),
        (9.8, None),
        (9.6, None),
        (9.4, None),
        (9.2, None),
        (9.0, None),
        (9.0, 10),
        (9.0, 8),
        (9.0, 7),
        (9.0, 6),
        (8.8, 6),
        (8.6, 6),
        (8.6, 5),
        (8.2, 5),
        (8.0, 4),
    )
)


def _pt(value: float) -> str:
    return f"{value:g}".replace(".", ",") + " pt"


@dataclass(frozen=True)
class FitReport:
    """Wynik dopasowania strony 1 — do komunikatu w interfejsie."""

    fits: bool
    font_pt: float
    skill_cap: Optional[int]
    steps: tuple[str, ...]  # zastosowane skrócenia, po polsku
    attempts: int
    free_mm: Optional[float] = None  # wolne miejsce na str. 1 przed rozsunięciem sekcji
    block_gap_mm: float = 0.0
    inner_mm: float = 0.0

    @property
    def settings(self) -> LayoutSettings:
        return LayoutSettings(
            font_pt=self.font_pt,
            skill_cap=self.skill_cap,
            block_gap_mm=self.block_gap_mm,
            inner_mm=self.inner_mm,
        )

    @property
    def summary(self) -> str:
        """„strona 1 mieści się · pismo 10 pt”."""
        head = "strona 1 mieści się" if self.fits else "strona 1 nie mieści się"
        return f"{head} · pismo {_pt(self.font_pt)}"


def describe(settings: LayoutSettings) -> tuple[str, ...]:
    steps = []
    if settings.font_pt < BASE_FONT_PT:
        steps.append(f"pismo strony 1: {_pt(settings.font_pt)}")
    if settings.skill_cap:
        steps.append(
            f"umiejętności: najwyżej {settings.skill_cap} pozycji w kategorii, pełna lista na str. 2"
        )
    return tuple(steps)


def page1_height_mm(document: Any) -> Optional[float]:
    """Wysokość bloku strony 1 z układu WeasyPrint (wewnętrzne drzewo pudełek;
    bez niego sekcje zostają nierozsunięte, a strona i tak się mieści)."""
    try:
        for box in document.pages[0]._page_box.descendants():
            element = getattr(box, "element", None)
            if element is not None and element.get("class") == "p1":
                return box.margin_height() * PX_TO_MM
    except Exception:  # noqa: BLE001 — pomiar jest dodatkiem, nie warunkiem renderu
        logger.warning("cv_new_layout: nie udało się zmierzyć strony 1", exc_info=True)
    return None


INNER_SHARE = 0.5  # część wolnego miejsca w środek sekcji, reszta między sekcje
INNER_MAX = 3.0
INNER_ROUNDS = 7


def _height(ctx: Ctx, settings: LayoutSettings) -> Optional[float]:
    document = html_to_document(build_html(ctx, settings, page1_only=True))
    if len(document.pages) != 1:
        return None
    return page1_height_mm(document)


def _inner_for(ctx: Ctx, settings: LayoutSettings, free: float) -> tuple[float, float]:
    """(luz w środku sekcji, wolne miejsce po nim) — wyszukiwanie połówkowe tak, żeby
    w środek poszła około połowa wolnego miejsca."""
    target = PAGE1_HEIGHT - free * (1 - INNER_SHARE)
    lo, hi, left = 0.0, INNER_MAX, free
    for _ in range(INNER_ROUNDS):
        mid = (lo + hi) / 2
        height = _height(ctx, replace(settings, inner_mm=mid))
        if height is not None and height <= target:
            lo, left = mid, PAGE1_HEIGHT - height
        else:
            hi = mid
    return lo, left


def fit_page1(ctx: Ctx) -> FitReport:
    for attempt, settings in enumerate(STEPS, start=1):
        html = build_html(ctx, settings, page1_only=True)
        document = html_to_document(html)
        if len(document.pages) != 1:
            continue
        height = page1_height_mm(document)
        free = max(PAGE1_HEIGHT - height, 0.0) if height is not None else None
        blocks = html.count("<div class='blk'>")
        inner, left = (0.0, free)
        if free and free > 2.0:
            inner, left = _inner_for(ctx, settings, free)
        gap = round(left / blocks, 2) if left and blocks else 0.0
        return FitReport(
            True,
            settings.font_pt,
            settings.skill_cap,
            describe(settings),
            attempt,
            free_mm=round(free, 1) if free is not None else None,
            block_gap_mm=gap,
            inner_mm=round(inner, 2),
        )
    last = STEPS[-1]
    return FitReport(False, last.font_pt, last.skill_cap, describe(last), len(STEPS))
