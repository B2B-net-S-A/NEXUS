"""Szablon graficzny strony kariery, grafiki OG i plakatu (0478, 19.10.2026).

Rekruter wybiera szablon w oknie „Udostępnij” (``job_public_profiles.theme``).
Bez wyboru szablon wynika z roli w tytule rekrutacji, a gdy tytuł nic nie mówi
— z kategorii kompetencji (decyzja Artura 19.10.2026). Sama kategoria nie
wystarcza: z 4473 rekrutacji z 12 miesięcy analitycy systemowi i testerzy
siedzą także w Infra i Management, więc analityk dostałby szablon DevOps.

Makiety: https://claude.ai/artifact/TFqDt54DUg4qRdyJXnu6wm (strona
„Najczęstsze role”). Kolory stron żyją we froncie (``components/career/
themes.ts``); tu tylko to, czego potrzebuje plakat PDF.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.job import Job

DEFAULT_THEME = "terminal"

# Kolejność = kolejność w oknie wyboru (najczęstsze role najpierw).
THEME_LABELS: dict[str, str] = {
    "terminal": "Terminal",
    "sekwencja": "Diagram sekwencji",
    "glitch": "Glitch",
    "konstelacja": "Konstelacja",
    "c4": "Architektura C4",
    "topologia": "Topologia sieci",
    "tablica": "Tablica warsztatowa",
    "plan": "Plan",
    "papier": "Papier",
    "radar": "Radar",
    "horyzont": "Horyzont",
    "szafa": "Szafa serwerowa",
}
THEMES: tuple[str, ...] = tuple(THEME_LABELS)

# Rola z tytułu — pierwsze dopasowanie wygrywa. Wzorce jak w zestawieniu ról
# z 19.10.2026; ``manual`` przed ogólnym testerem, analityk biznesowy przed
# systemowym („analityk biznesowo-systemowy” prowadzi warsztaty).
_ROLE_RULES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (theme, re.compile(pattern))
    for theme, pattern in (
        (
            "plan",
            r"project manager|kierownik projekt|program manager|delivery manager"
            r"|scrum|\bpmo\b|agile coach|product owner",
        ),
        ("c4", r"architekt|architect"),
        ("tablica", r"analityk biznes|business analyst|biznesowo"),
        ("sekwencja", r"analityk system|system analyst|\bit analyst|analityk it"),
        ("papier", r"(test|\bqa\b).*manual|manual.*(test|\bqa\b)"),
        ("glitch", r"test|\bqa\b|sdet|quality assurance"),
        ("radar", r"bezpiecze|security|cyber|\bsoc\b|pentest"),
        ("topologia", r"devops|\bsre\b|platform engineer|cloud|kubernetes|chmur"),
        (
            "konstelacja",
            r"\bdata\b|danych|\betl\b|\bbi\b|power bi|hurtown"
            r"|machine learning|\bml\b|\bai\b",
        ),
        ("szafa", r"administrator|\badmin\b|sieci|network|linux|windows|infrastruktur"),
        ("horyzont", r"front|react|angular|\bvue\b|full.?stack"),
        ("terminal", r"java|\.net|c#|python|backend|programista|developer"),
    )
)

# Dla tytułów bez rozpoznanej roli (26% z 12 miesięcy: „PL”, nazwa projektu).
_CATEGORY_THEME: dict[str, str] = {
    "software_development": "terminal",
    "infrastructure_operations": "topologia",
    "security_quality": "glitch",
    "management_delivery": "plan",
    "data_ai": "konstelacja",
}

# Plakat A4 (WeasyPrint) — ten sam kolor co strona; kontrast tekstu ≥ 4,5:1.
POSTER_COLORS: dict[str, dict[str, str]] = {
    "terminal": {
        "bg": "#000000",
        "text": "#F5F5F5",
        "accent": "#F06A80",
        "muted": "#A5A5A5",
    },
    "sekwencja": {
        "bg": "#0F1222",
        "text": "#EEF1FF",
        "accent": "#A78BFA",
        "muted": "#CBD0EE",
    },
    "glitch": {
        "bg": "#0A0A0A",
        "text": "#FAFAFA",
        "accent": "#00E1FF",
        "muted": "#C8C8C8",
    },
    "konstelacja": {
        "bg": "#070A1A",
        "text": "#EEF0FF",
        "accent": "#F4D58D",
        "muted": "#C9CDEA",
    },
    "c4": {"bg": "#0B0F14", "text": "#E8EEF4", "accent": "#FF8A65", "muted": "#C8D2DC"},
    "topologia": {
        "bg": "#0A0E14",
        "text": "#F1F5F9",
        "accent": "#FFA94D",
        "muted": "#C3CDD9",
    },
    "tablica": {
        "bg": "#13110E",
        "text": "#F7F3EC",
        "accent": "#FFC857",
        "muted": "#DDD5C8",
    },
    "plan": {
        "bg": "#0B2A4A",
        "text": "#FFFFFF",
        "accent": "#9CD3FF",
        "muted": "#D3E3F3",
    },
    "papier": {
        "bg": "#F5F3EE",
        "text": "#1A1A1A",
        "accent": "#C8102E",
        "muted": "#3B3832",
    },
    "radar": {
        "bg": "#04120F",
        "text": "#E6FFF6",
        "accent": "#43F5B5",
        "muted": "#BFDCD2",
    },
    "horyzont": {
        "bg": "#0A0614",
        "text": "#F5F0FF",
        "accent": "#FF6AD5",
        "muted": "#D2C8E6",
    },
    "szafa": {
        "bg": "#0A0C0F",
        "text": "#E6EBF0",
        "accent": "#60A5FA",
        "muted": "#C3CCD6",
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
    """Domyślny szablon rekrutacji: rola z tytułu → kategoria → Terminal."""
    return (
        role_theme(title) or _CATEGORY_THEME.get(category_slug or "") or DEFAULT_THEME
    )


def resolve_theme(
    stored: Optional[str], title: Optional[str], category_slug: Optional[str]
) -> str:
    """Szablon, który widzi kandydat. Wybór rekrutera wygrywa, o ile istnieje."""
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
