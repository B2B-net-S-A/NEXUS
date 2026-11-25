"""Układ CV klasyczny / „Nowe CV” — reguły bez bazy (`services/cv_layout.py`)."""

from pathlib import Path

import pytest

from app.core.config import settings
from app.services import cv_layout
from app.services.cv_layout_schema import ALL_DDL, ADDED_COLUMNS
from app.services.cv_new_pdf import NewCvPdf


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", True)


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", False)


def test_flag_off_means_classic_everywhere(flag_off):
    assert cv_layout.enabled() is False
    assert cv_layout.effective("new") == "classic"
    assert cv_layout.requested("new") is None


def test_flag_on_keeps_stored_layout(flag_on):
    assert cv_layout.effective("new") == "new"
    assert cv_layout.effective("classic") == "classic"
    assert cv_layout.effective(None) == "classic"
    assert cv_layout.requested("new") == "new"
    assert cv_layout.requested(None) is None
    with pytest.raises(ValueError):
        cv_layout.requested("fancy")


def test_rule_layout_defaults_to_classic():
    class Rule:
        cv_layout = "new"

    assert cv_layout.rule_layout(Rule()) == "new"
    assert cv_layout.rule_layout(None) == "classic"
    assert cv_layout.rule_layout(object()) == "classic"


def test_page1_why_is_three_slots():
    assert cv_layout.page1_why(None) is None
    assert cv_layout.page1_why({"why": "tekst"}) is None
    assert cv_layout.page1_why({"why": ["", "  "]}) is None
    # Pusty slot zostaje na swoim miejscu — bierze punkt generatora.
    assert cv_layout.page1_why({"why": ["a", "", "b", "c", "d"]}) == ["a", "", "b"]
    assert cv_layout.page1_why({"why": [None, "b"]}) == ["", "b", ""]


def test_page1_composition_e2_result_replaces_third_point():
    points = ["Lata.", "Technologie.", "Wymaganie.", "Czwarty."]
    assert cv_layout.compose_page1_why(points, None) is None
    unverified = {"results": [{"text": "Wynik bez cytatu.", "verified": False}]}
    assert cv_layout.compose_page1_why(points, unverified) is None
    extras = {
        "results": [
            {"text": "Wynik A.", "verified": True},
            {"text": "Wynik B.", "verified": True},
        ],
        "result_index": 1,
    }
    assert cv_layout.compose_page1_why(points, extras) == [
        "Lata.",
        "Technologie.",
        "Wynik B.",
    ]
    assert cv_layout.compose_page1_why(points, {**extras, "result_index": 9}) == [
        "Lata.",
        "Technologie.",
        "Wynik A.",
    ]
    manual = {**extras, "result_text": "Mój wynik."}
    assert cv_layout.compose_page1_why(points, manual)[2] == "Mój wynik."
    edited = {**extras, "why": ["Moje 1.", "Moje 2.", "Moje 3."]}
    assert cv_layout.compose_page1_why(points, edited) == [
        "Moje 1.",
        "Moje 2.",
        "Moje 3.",
    ]


def test_page1_composition_fills_each_empty_slot_with_todays_point():
    points = ["Lata.", "Technologie.", "Wymaganie."]
    only_task = {"why": ["", "", "Zadanie z dowodem."]}
    assert cv_layout.compose_page1_why(points, only_task) == [
        "Lata.",
        "Technologie.",
        "Zadanie z dowodem.",
    ]
    # Slot 3 bez zdania: najmocniejszy wynik, a bez niego punkt 3 generatora.
    result = {
        "why": ["Zdanie 1.", "", ""],
        "results": [{"text": "Wynik.", "verified": True}],
    }
    assert cv_layout.compose_page1_why(points, result) == [
        "Zdanie 1.",
        "Technologie.",
        "Wynik.",
    ]
    assert cv_layout.compose_page1_why(points, {"why": ["Zdanie 1."]}) == [
        "Zdanie 1.",
        "Technologie.",
        "Wymaganie.",
    ]
    assert cv_layout.compose_page1_why([], {"why": ["", "Tylko 2."]}) == ["Tylko 2."]


def test_pdf_route_layout_choice(flag_on, monkeypatch):
    from app.api.cv_pdf_preview import _wanted_layout

    assert _wanted_layout(None, "new") == "new"
    assert _wanted_layout(None, None) == "classic"
    assert _wanted_layout("classic", "new") == "classic"
    assert _wanted_layout("new", "classic") == "new"
    assert _wanted_layout("bogus", "new") == "new"
    monkeypatch.setattr(settings, "CV_NEW_LAYOUT_ENABLED", False)
    assert _wanted_layout("new", "new") == "classic"


def test_new_pdf_headers_tell_the_preview_about_page_one():
    result = NewCvPdf(
        pdf=b"%PDF",
        fits=True,
        font_pt=9.5,
        steps=("skills-cap",),
        unmapped_sections=("Hobby",),
    )
    assert result.headers() == {
        "X-CV-Layout": "new",
        "X-CV-Page1-Fits": "1",
        "X-CV-Page1-Font": "9.5",
        "X-CV-Unmapped-Sections": "1",
    }


def test_new_pdf_headers_are_exposed_to_the_browser():
    source = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    for header in NewCvPdf(b"", True, 10, (), ()).headers():
        assert f'"{header}"' in source


def test_schema_ddl_is_idempotent_and_mirrored_in_entrypoint():
    assert len(ALL_DDL) == len(ADDED_COLUMNS)
    assert all("ADD COLUMN IF NOT EXISTS" in stmt for stmt in ALL_DDL)
    entrypoint = (Path(__file__).parents[1] / "entrypoint.sh").read_text()
    assert "from app.services import cv_layout_schema" in entrypoint
    assert "*_CV_LAYOUT_DDL," in entrypoint
