"""Dodatki strony 1 „Nowego CV” — bez wyboru wieńca (od 25.11.2026 wieniec tylko przy
wyróżniku) i wymagania MUST — bez bazy."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.cv_page1 import Page1Update, _merged
from app.services.cv_new_pdf import must_names


def test_wreath_choice_is_no_longer_part_of_the_request():
    """Artur 25.11.2026: wieniec tylko przy wyróżniku — wyboru wieńca w Edukacji nie ma."""
    assert "wreath" not in Page1Update.model_fields
    extras = {"why": ["a"], "wreath": "cert"}
    # stary wpis w dodatkach zostaje nietknięty (render go nie czyta)
    assert _merged(extras, Page1Update(result_text="Zdanie"))["wreath"] == "cert"


def test_must_names_reads_champion_stack():
    profile = {
        "stack": {"must": [{"name": "PRINCE2 Practitioner"}, "Java", {"name": " "}, {}]}
    }
    assert must_names(profile) == ("PRINCE2 Practitioner", "Java")
    assert must_names(None) == () and must_names({"stack": []}) == ()


def test_merged_keeps_http_errors_for_bad_result_index():
    with pytest.raises(HTTPException):
        _merged({}, Page1Update(result_index=3))
