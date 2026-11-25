"""Języki na stronie 1 „Nowego CV” — zapis z myślnikiem bez spacji (pętla jakości 25.11.2026)."""

from __future__ import annotations

import pytest

from app.services.cv_new_layout.facts import lang_code, lang_parts


@pytest.mark.parametrize(
    ("entry", "name", "level"),
    [
        ("Polish-fluent.", "Polish", "fluent"),
        ("polski-ojczysty", "polski", "ojczysty"),
        ("Serbo-Croatian", "Serbo-Croatian", ""),
        ("English - C1", "English", "C1"),
    ],
)
def test_language_with_hyphen_without_spaces(entry, name, level):
    """#40503: „Polish-fluent.” dawało pastylkę „PO” bez poziomu; myślnik bez spacji dzieli
    tylko po znanej nazwie języka."""
    assert lang_parts(entry) == (name, level)
    if name.lower() in ("polish", "polski"):
        assert lang_code(name) == "PL"
