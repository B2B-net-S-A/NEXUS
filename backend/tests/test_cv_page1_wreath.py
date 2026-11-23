"""Wybór wieńca na stronie 1 „Nowego CV” (23.11.2026) — bez bazy."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api.cv_page1 import Page1Update, _merged
from app.services.cv_layout import page1_wreath
from app.services.cv_new_pdf import must_names


def test_wreath_choice_is_stored_and_auto_clears_it():
    extras = {"results": [{"text": "x", "verified": True}], "why": ["a"]}
    merged = _merged(extras, Page1Update(wreath="cert"))
    assert merged["wreath"] == "cert" and merged["why"] == ["a"]
    assert "wreath" not in _merged(merged, Page1Update(wreath="auto"))


def test_unknown_wreath_value_is_rejected():
    with pytest.raises(ValueError):
        Page1Update(wreath="dyplom")


def test_page1_wreath_defaults_to_auto():
    assert page1_wreath(None) == "auto"
    assert page1_wreath({"wreath": "school"}) == "school"
    assert page1_wreath({"wreath": "coś"}) == "auto"


def test_must_names_reads_champion_stack():
    profile = {"stack": {"must": [{"name": "PRINCE2 Practitioner"}, "Java", {"name": " "}, {}]}}
    assert must_names(profile) == ("PRINCE2 Practitioner", "Java")
    assert must_names(None) == () and must_names({"stack": []}) == ()


def test_merged_keeps_http_errors_for_bad_result_index():
    with pytest.raises(HTTPException):
        _merged({}, Page1Update(result_index=3))
