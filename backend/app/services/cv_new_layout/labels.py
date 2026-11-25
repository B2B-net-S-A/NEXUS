"""Stałe teksty układu „Nowe CV” po polsku i angielsku.

Tam, gdzie to samo pojęcie ma już plik Word (`docx_renderer.TRANSLATIONS`),
brzmienie jest to samo, żeby Word i PDF mówiły jednym głosem; pilnuje tego
`tests/test_cv_new_layout_text.py`. Klauzula RODO i nagłówek zrzutu zgody
są czytane wprost z `TRANSLATIONS` (długi tekst prawny nie ma drugiej kopii).
"""

from __future__ import annotations

LABELS: dict[str, dict[str, str]] = {
    "pl": {
        # te same słowa co w docx_renderer.TRANSLATIONS (bez wersalików i dwukropków)
        "why": "Dlaczego nasz kandydat",
        "education": "Edukacja",
        "certs_training": "Certyfikaty i szkolenia",
        "schooling_head": "Wykształcenie",
        "other_certs": "Inne certyfikaty i szkolenia",
        "skills": "Umiejętności",
        "experience": "Doświadczenie",
        "company": "Nazwa firmy",
        "position": "Stanowisko",
        "tasks": "Zakres zadań",
        "technologies": "Technologie",
        "certifications": "Certyfikaty",
        "dates": "Daty",
        # tryb blind, jak w docx_renderer.render_cv_to_bytes i html_export
        "why_blind": "Podsumowanie",
        # tylko w tym układzie
        "career": "Przebieg kariery",
        "key_for_job": "Kluczowe dla tej rekrutacji",
        "period": "Okres",
        "today": "dziś",
        "current": "obecnie",
        "native": "ojczysty",
        "including": "m.in.",
        "earlier": "Wcześniej",
        "highlight_client": "Doświadczenie w {client}",
        "highlight_client_text": "**{duration} jako {position}** w {client}.",
        "highlight_client_text_short": "**{duration}** w {client}.",
        "year": "Rok",
        "certificate": "Certyfikat",
        "school": "Szkoła",
        "field_degree": "Kierunek i tytuł",
        "diploma": "Dyplom",
        "schooling": "Wykształcenie",
        "skills_full": "Umiejętności — pełna lista",
        "education_full": "Edukacja — pełna lista",
        "skills_more_note": "+N to kolejne pozycje tej kategorii — pełna lista na str. 2.",
        "more_at_end": "pełna lista na końcu CV",
        "more_on_page2": "pełna lista na str. 2",
        "about": "ok.",
        "months_short": "mies.",
        "footer": "B2B.net S.A. · Al. Jerozolimskie 180, 02-486 Warszawa · KRS 0000387063 · NIP 5711707392",
        "doc_title": "CV",
    },
    "en": {
        "why": "Why our candidate",
        "education": "Education",
        "certs_training": "Certifications and training",
        "schooling_head": "Degree",
        "other_certs": "Other certifications and training",
        "skills": "Skills",
        "experience": "Experience",
        "company": "Company",
        "position": "Position",
        "tasks": "Tasks",
        "technologies": "Technologies",
        "certifications": "Certifications",
        "dates": "Dates",
        "why_blind": "Summary",
        "career": "Career path",
        "key_for_job": "Key for this role",
        "period": "Period",
        "today": "today",
        "current": "present",
        "native": "native",
        "including": "incl.",
        "earlier": "Earlier",
        "highlight_client": "Experience at {client}",
        "highlight_client_text": "**{duration} as {position}** at {client}.",
        "highlight_client_text_short": "**{duration}** at {client}.",
        "year": "Year",
        "certificate": "Certification",
        "school": "School",
        "field_degree": "Field and degree",
        "diploma": "Diploma",
        "schooling": "Education",
        "skills_full": "Skills — full list",
        "education_full": "Education — full list",
        "skills_more_note": "+N are further items of the category — full list on page 2.",
        "more_at_end": "full list at the end of the CV",
        "more_on_page2": "full list on page 2",
        "about": "approx.",
        "months_short": "mo.",
        "footer": "B2B.net S.A. · Al. Jerozolimskie 180, 02-486 Warsaw · KRS 0000387063 · NIP 5711707392",
        "doc_title": "CV",
    },
}

# (jedna, kilka, wiele) — polska odmiana 1 / 2–4 / 5+; angielska 1 / reszta
_NOUNS: dict[str, dict[str, tuple[str, str, str]]] = {
    "pl": {
        "year": ("rok", "lata", "lat"),
        "position": ("stanowisko", "stanowiska", "stanowisk"),
        "school": ("szkoła", "szkoły", "szkół"),
        "certificate": ("certyfikat", "certyfikaty", "certyfikatów"),
        "short_project": ("krótki projekt", "krótkie projekty", "krótkich projektów"),
        "category": ("kategoria", "kategorie", "kategorii"),
    },
    "en": {
        "year": ("year", "years", "years"),
        "position": ("position", "positions", "positions"),
        "school": ("school", "schools", "schools"),
        "certificate": ("certification", "certifications", "certifications"),
        "short_project": ("short project", "short projects", "short projects"),
        "category": ("category", "categories", "categories"),
    },
}


def plural_pl(n: int, one: str, few: str, many: str) -> str:
    """Polska odmiana po liczbie: 1 rok, 2–4 lata (bez 12–14), 5 lat."""
    if n == 1:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def language_of(code: str) -> str:
    return code if code in LABELS else "pl"


def labels_for(code: str) -> dict[str, str]:
    return LABELS[language_of(code)]


def noun(code: str, key: str, n: int) -> str:
    """Rzeczownik w formie pasującej do liczby n („3 lata”, „3 years”)."""
    one, few, many = _NOUNS[language_of(code)][key]
    if language_of(code) == "en":
        return one if n == 1 else many
    return plural_pl(n, one, few, many)


def counted(code: str, key: str, n: int) -> str:
    return f"{n} {noun(code, key, n)}"


def more_at_end(code: str, key: str, n: int) -> str:
    """„+ 2 szkoły — pełna lista na końcu CV”."""
    return f"+ {counted(code, key, n)} — {labels_for(code)['more_at_end']}"


def more_on_page2(code: str, key: str, n: int) -> str:
    """„+ 5 kategorii — pełna lista na str. 2”."""
    return f"+ {counted(code, key, n)} — {labels_for(code)['more_on_page2']}"


def _translations() -> dict[str, dict[str, str]]:
    # Leniwie: docx_renderer ciągnie python-docx, a sam układ PDF go nie potrzebuje.
    from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS

    return TRANSLATIONS


def default_rodo_clause(code: str) -> str:
    """Klauzula zgody z szablonu Worda (zwykły tekst, nie HTML)."""
    return _translations()[language_of(code)]["rodo"]


def consent_heading(code: str) -> str:
    return _translations()[language_of(code)]["consent_heading"]
