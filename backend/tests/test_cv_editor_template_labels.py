"""Etykiety szablonu w edytorze CV są lustrem szablonu Worda.

Edytor wstawia bloki z tekstem etykiet (``frontend/src/lib/cv-editor-blocks.ts``),
a serwer rozpoznaje je po DOKŁADNYM tekście z ``docx_renderer.TRANSLATIONS``.
Zmiana po jednej stronie dawałaby w Wordzie zwykły akapit zamiast etykiety
albo klauzulę zgody, której edytor nie zablokuje.
"""

import re
from pathlib import Path

import pytest

from app.services.cv_generator_b2b.docx_renderer import TRANSLATIONS
from app.services.cv_rodo_clause import is_rodo_text

FRONTEND = Path(__file__).resolve().parents[2] / "frontend/src"
BLOCKS = (FRONTEND / "lib/cv-editor-blocks.ts").read_text(encoding="utf-8")
PAPER_CSS = (FRONTEND / "app/globals.css").read_text(encoding="utf-8")

# Klucz edytora → klucz szablonu (różni się tylko sekcja narracyjna).
TEMPLATE_KEYS = {
    "why_points": "why",
    "education": "education",
    "skills": "skills",
    "certifications": "certifications",
    "languages": "languages",
    "experience": "experience",
    "responsibilities": "responsibilities",
    "technologies": "technologies",
}


def _ts_object(name: str) -> dict[str, dict[str, str]]:
    """``export const NAME = { pl: {...}, en: {...} }`` → słownik."""
    body = re.search(rf"export const {name} = \{{(.*?)\n\}} as const", BLOCKS, re.S)
    assert body, f"nie ma stałej {name} w cv-editor-blocks.ts"
    result: dict[str, dict[str, str]] = {}
    for lang, entries in re.findall(r"\b(pl|en): \{(.*?)\}", body.group(1), re.S):
        result[lang] = dict(re.findall(r'(\w+): "([^"]*)"', entries))
    return result


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_inserted_labels_match_the_word_template(lang):
    labels = _ts_object("CV_TEMPLATE_LABELS")[lang]
    assert set(labels) == set(TEMPLATE_KEYS)
    for editor_key, template_key in TEMPLATE_KEYS.items():
        assert labels[editor_key] == TRANSLATIONS[lang][template_key], editor_key


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_clause_opening_locked_by_the_editor_is_the_one_the_server_recognises(lang):
    openings = dict(
        re.findall(
            r'(pl|en): "([^"]+)"',
            re.search(r"export const CV_RODO_OPENINGS = \{(.*?)\}", BLOCKS, re.S).group(
                1
            ),
        )
    )
    clause = TRANSLATIONS[lang]["rodo"]
    assert clause.startswith(openings[lang])
    assert is_rodo_text(openings[lang] + " dalszy ciąg")


@pytest.mark.parametrize("lang", ["pl", "en"])
def test_paper_hints_use_the_template_wording(lang):
    """Podpowiedzi „Stanowisko:” / „Nazwa firmy:” na kartce to tekst z Worda."""
    for key in ("position", "company_name"):
        assert f'content: "{TRANSLATIONS[lang][key]} ";' in PAPER_CSS, key
