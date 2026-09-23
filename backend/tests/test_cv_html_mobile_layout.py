"""Publiczne CV (/cv/{token}, /cv/i/{token}, plik HTML) czytelne na telefonie.

Audyt responsywności 23.09.2026 (P0): szablon brandowanego CV miał sztywną
siatkę ``230px 1fr`` i tylko ``@media print`` — przy ~340 px iframe'a na treść
doświadczenia zostawało ~40 px, słowo na linię. Oba szablony muszą mieć
zapytanie dla wąskiego ekranu.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

from app.services.cv_generator_b2b.html_export import render_interactive_html
from app.services.cv_html_renderer import _generate_cv_html


def _media_block(html: str, query: str) -> str:
    start = html.index(query)
    # Blok kończy się pierwszym zamknięciem na poziomie zapytania.
    depth = 0
    for i in range(html.index("{", start), len(html)):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                return html[start : i + 1]
    raise AssertionError("niezamknięty blok @media")


def _candidate() -> SimpleNamespace:
    return SimpleNamespace(
        name="Jan",
        lastname="Mobilny",
        email=None,
        phone=None,
        location=None,
        linkedin=None,
        ai_summary="",
        skills=[],
        experience=[],
        education=[],
        languages=[],
        competence_category=None,
        years_experience=None,
    )


def test_branded_cv_stacks_sidebar_on_narrow_screens():
    html = _generate_cv_html(_candidate(), "standard", "pl")
    block = _media_block(html, "@media (max-width: 640px)")
    assert re.search(r"\.cv-body\s*\{\s*grid-template-columns:\s*1fr", block)
    assert re.search(r"\.cv-header-date\s*\{[^}]*position:\s*static", block)
    assert re.search(r"\.cv-main\s*\{[^}]*padding:\s*20px 16px", block)
    # Druk zostaje osobnym zapytaniem, nietkniętym.
    assert "@media print" in html


def test_interactive_html_export_shrinks_padding_on_narrow_screens():
    html = render_interactive_html(
        {"name": "Jan Mobilny", "experience": [], "education": []}, []
    )
    block = _media_block(html, "@media (max-width: 600px)")
    assert re.search(r"\.cv\s*\{\s*padding:\s*20px 16px", block)
    assert re.search(r"\.edu\s*\{[^}]*flex-direction:\s*column", block)
