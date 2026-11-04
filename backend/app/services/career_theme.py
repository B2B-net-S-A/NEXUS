"""Szablon graficzny strony kariery, grafiki OG i plakatu.

Rekruter wybiera szablon w oknie „Udostępnij” (``job_public_profiles.theme``).
Bez wyboru szablon wynika z roli w tytule rekrutacji, a gdy tytuł nic nie mówi
— z kategorii kompetencji (decyzja Artura 19.10.2026). Sama kategoria nie
wystarcza: z 4473 rekrutacji z 12 miesięcy analitycy systemowi i testerzy
siedzą także w Infra i Management.

Od 28.10.2026 (feedback zespołu do ogłoszeń: „nieczytelne”, „nie w szacie
B2B”, „jakby się nie doładowało”) są trzy szablony w barwach B2B Network
zamiast 12 scen ról: Terminal dla ról deweloperskich, Jasny dla biznesowych
i Grafit dla reszty. Makiety: https://claude.ai/artifact/RGquQpMFyKgRYHPognJ2kU.
Wybory z 12 scen zostają w bazie, ale ``resolve_theme`` traktuje je jak brak
wyboru — opublikowane linki dostają nowy wygląd bez ponownego zatwierdzania.
Kolory stron żyją we froncie (``components/career/themes.ts``); tu tylko to,
czego potrzebuje plakat PDF.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.job import Job

DEFAULT_THEME = "grafit"

# Kolejność = kolejność w oknie wyboru (domyślny najpierw).
THEME_LABELS: dict[str, str] = {
    "grafit": "Grafit B2B",
    "terminal": "Terminal",
    "jasny": "Jasny B2B",
}
THEMES: tuple[str, ...] = tuple(THEME_LABELS)

# Rola z tytułu — pierwsze dopasowanie wygrywa. Architekt przed programistą
# („Java Solution Architect”), analityk przed „data” („Data Analyst” czyta
# wymagania jak analityk), role zarządcze przed resztą.
_ROLE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (theme, re.compile(pattern))
    for theme, pattern in (
        ("grafit", r"architekt|architect"),
        (
            "jasny",
            r"project manager|kierownik projekt|program(me)? manager"
            r"|delivery (manager|lead)|scrum|\bpmo\b|agile coach|product owner"
            r"|analityk|analyst",
        ),
        (
            "terminal",
            r"test|\bqa\b|sdet|quality assurance"
            r"|devops|\bsre\b|platform engineer"
            r"|front|react|angular|\bvue\b|full.?stack"
            r"|java|\.net|c#|python|backend|programista|developer",
        ),
        (
            "grafit",
            r"bezpiecze|security|cyber|\bsoc\b|pentest"
            r"|cloud|kubernetes|chmur"
            r"|\bdata\b|danych|\betl\b|\bbi\b|power bi|hurtown"
            r"|machine learning|\bml\b|\bai\b"
            r"|administrator|\badmin\b|sieci|network|linux|windows|infrastruktur",
        ),
    )
)

# Dla tytułów bez rozpoznanej roli (26% z 12 miesięcy: „PL”, nazwa projektu).
_CATEGORY_THEME: dict[str, str] = {
    "software_development": "terminal",
    "security_quality": "terminal",
    "management_delivery": "jasny",
}

# Plakat A4 (WeasyPrint) — ten sam kolor co strona; kontrast tekstu ≥ 4,5:1.
POSTER_COLORS: dict[str, dict[str, str]] = {
    "grafit": {
        "bg": "#141414",
        "text": "#F5F4EC",
        "accent": "#F05A69",
        "muted": "#D9D6CC",
    },
    "terminal": {
        "bg": "#161514",
        "text": "#F1EEE6",
        "accent": "#F05A69",
        "muted": "#CFCAC0",
    },
    "jasny": {
        "bg": "#F5F4EC",
        "text": "#141414",
        "accent": "#C42536",
        "muted": "#2E3236",
    },
}


def role_theme(title: Optional[str]) -> Optional[str]:
    """Szablon z roli w tytule albo ``None``, gdy tytuł nie mówi, kogo szukamy."""
    text = (title or "").lower()
    for theme, pattern in _ROLE_RULES:
        if pattern.search(text):
            return theme
    return None


def default_theme(title: Optional[str], category_slug: Optional[str]) -> str:
    """Domyślny szablon rekrutacji: rola z tytułu → kategoria → Grafit."""
    return (
        role_theme(title) or _CATEGORY_THEME.get(category_slug or "") or DEFAULT_THEME
    )


def resolve_theme(
    stored: Optional[str], title: Optional[str], category_slug: Optional[str]
) -> str:
    """Szablon, który widzi kandydat. Wybór rekrutera wygrywa, o ile istnieje.

    Wybór jednej z 12 dawnych scen (do 28.10.2026) nie jest już szablonem —
    strona pokazuje wtedy domyślny szablon roli.
    """
    if stored in THEME_LABELS:
        return stored
    return default_theme(title, category_slug)


async def job_category_slug(db: "AsyncSession", job: "Job") -> Optional[str]:
    """Slug kategorii rekrutacji — jawne zapytanie, bo relacja ładuje się leniwie."""
    if job.competence_category_id is None:
        return None
    from sqlalchemy import select

    from app.models.competence_category import CompetenceCategory

    return await db.scalar(
        select(CompetenceCategory.slug).where(
            CompetenceCategory.id == job.competence_category_id
        )
    )
