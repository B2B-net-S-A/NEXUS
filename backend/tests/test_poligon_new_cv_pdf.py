"""Podgląd „Nowego CV” na Poligonie (`scripts/poligon_new_cv_pdf.py`, 25.11.2026).

Skrypt czyta fikcyjne CV z `frontend/src/lib/poligon/cv-fiction.ts`; parser
literałów TS sprawdzamy bez WeasyPrint. Render (gdy WeasyPrint jest) pilnuje,
że strona 1 się mieści, a pismo zgadza się z nagłówkiem `X-CV-Page1-Font`
w `adapter.ts` — pasek „Strona 1 z N · mieści się · pismo N pt” na Poligonie.
"""

from __future__ import annotations

import re

import pytest

from scripts import poligon_new_cv_pdf as script

ADAPTER = script.REPO / "frontend/src/lib/poligon/adapter.ts"


def _source() -> str:
    return script.FICTION.read_text(encoding="utf-8")


def test_html_z_cv_fiction_bez_nazwiska_i_komentarzy():
    html = script.fiction_html(_source())
    assert html.startswith("<h1>Senior Project Manager</h1>")
    assert "${" not in html and "//" not in html
    for section in (
        "why_points",
        "education",
        "certifications",
        "skills",
        "experience",
    ):
        assert f'data-cv-section="{section}"' in html
    assert html.count('data-cv-section="role"') == 3


def test_html_z_nazwiskiem_osoby():
    html = script.fiction_html(_source(), "Anna Ćwiczebna")
    assert html.startswith("<h1>Senior Project Manager – Anna Ćwiczebna</h1>")


def test_zdania_strony_1_z_cv_fiction_why():
    why = script.fiction_why(_source())
    assert [item["slot"] for item in why] == ["experience", "requirements", "key_task"]
    assert all(item["verified"] is True for item in why)
    assert why[1]["evidence"][0]["must"] == "Scrum"
    assert why[0]["roles"] == [0, 1, 2]


def test_render_miesci_strone_1_jak_naglowek_poligonu():
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as exc:  # brak libpango kończy import OSError
        pytest.skip(f"WeasyPrint niedostępny: {exc}")
    result = script.render(_source())
    font = re.search(
        r'"X-CV-Page1-Font": "([\d.]+)"', ADAPTER.read_text(encoding="utf-8")
    )
    assert result.fits
    assert font and float(font.group(1)) == result.font_pt
    assert result.unmapped_sections == ()
