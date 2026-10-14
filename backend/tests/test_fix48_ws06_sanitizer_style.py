"""Sanitizer CV: urwany napis w ``style`` nie rośnie przy każdym zapisie (audyt 13.10.2026).

tinycss2 czyta ``font-size: 'abc`` jako napis z błędem „koniec w środku
napisu” ukrytym w wartości deklaracji, a sanitizer odrzucał tylko błędy na
poziomie listy deklaracji. Zapis bez zamykającego cudzysłowu wracał przy
następnym przebiegu jako napis z kolejnymi średnikami: ``"abc;;`` → ``"abc;;;;``.
Wynik sanitizera jest porównywany przy ponownym zatwierdzeniu i w skrótach
kontroli AI, więc każdy zapis tej samej treści dawał inną treść.
"""

from __future__ import annotations

import pytest

from app.services.html_sanitizer import sanitize_cv_html


@pytest.mark.parametrize(
    "style",
    [
        "font-size: 'abc",
        'font-size: "abc',
        "color: red; font-size: 'abc",
        "color:red; font-family: 'Arial",
        "font-family: f('abc",
        "font-family: (a, 'b",
        "color: red; margin: 0 \\",
    ],
)
def test_sanitizing_twice_gives_the_same_html(style: str) -> None:
    once = sanitize_cv_html(f'<p style="{style.replace(chr(34), "&quot;")}">tekst</p>')
    assert sanitize_cv_html(once) == once, once
    assert sanitize_cv_html(sanitize_cv_html(once)) == once


@pytest.mark.parametrize(
    ("style", "kept"),
    [
        ("color: red; font-size: 'abc", "color: red;"),
        ("color:red; font-family: 'Arial", "color:red;"),
    ],
)
def test_unterminated_string_drops_only_its_declaration(style: str, kept: str) -> None:
    assert (
        sanitize_cv_html(f'<p style="{style}">tekst</p>')
        == f'<p style="{kept}">tekst</p>'
    )


def test_closed_string_in_style_stays() -> None:
    html = "<p style='font-family: \"Ari;al\";'>tekst</p>"
    assert sanitize_cv_html(html) == html
