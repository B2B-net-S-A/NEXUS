"""Szablon graficzny strony kariery: rola z tytułu, potem kategoria.

Decyzja Artura 19.10.2026: domyślny szablon wynika z roli w tytule rekrutacji,
a gdy tytuł nic nie mówi — z kategorii kompetencji. Od 28.10.2026 (feedback
zespołu: „nieczytelne”, „nie w szacie B2B”) są trzy szablony zamiast 12 scen:
Terminal dla ról deweloperskich, Jasny dla biznesowych, Grafit dla reszty.
"""

from __future__ import annotations

import pytest

from app.services import career_theme as ct


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Starszy programista Java", "terminal"),
        ("Senior Java Developer", "terminal"),
        ("Projektant Programista ds. Utrzymania Hurtowni Danych", "terminal"),
        ("Tester automatyzujący", "terminal"),
        ("PL - MDM - IT Automation Tester Senior - TP#41745", "terminal"),
        ("Tester manualny", "terminal"),
        ("DevOps Engineer", "terminal"),
        ("Frontend Developer", "terminal"),
        ("Fullstack Developer", "terminal"),
        ("Kierownik projektu", "jasny"),
        ("Project Manager for Core Technology Projects", "jasny"),
        ("Scrum Master", "jasny"),
        ("PMO Specialist", "jasny"),
        ("PL_EU AMLR Package - KYC delivery lead", "jasny"),
        ("Analityk biznesowy senior", "jasny"),
        ("Starszy Analityk Biznesowo-Systemowy", "jasny"),
        ("Analityk systemowy mid", "jasny"),
        ("IT Analyst", "jasny"),
        ("Architekt rozwiązań IT senior", "grafit"),
        ("Solution Architect", "grafit"),
        ("Data Engineer", "grafit"),
        ("Security Engineer", "grafit"),
        ("Administrator systemów Linux", "grafit"),
        ("Network SME – Data & Management Traffic Segregation PL", "grafit"),
        ("Cloud Engineer (Azure)", "grafit"),
    ],
)
def test_role_from_title(title: str, expected: str) -> None:
    assert ct.default_theme(title, None) == expected


@pytest.mark.parametrize(
    "title",
    ["PL", "", "Nordea: PL", "Konsultant GCOP", "On hold"],
)
def test_title_without_a_role_gives_none(title: str) -> None:
    assert ct.role_theme(title) is None


def test_not_every_automation_is_a_tester() -> None:
    # „automatyzacja” bez testów to np. RPA — nie szablon testera.
    assert ct.role_theme("Specjalista ds. automatyzacji procesów") is None


def test_architect_is_not_a_developer() -> None:
    # „Software Architect” ma w tytule „software”, ale to nie programista.
    assert ct.default_theme("Java Solution Architect", None) == "grafit"


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("software_development", "terminal"),
        ("security_quality", "terminal"),
        ("management_delivery", "jasny"),
        ("infrastructure_operations", "grafit"),
        ("data_ai", "grafit"),
        (None, "grafit"),
        ("cos_nowego", "grafit"),
    ],
)
def test_category_fallback(slug, expected) -> None:
    assert ct.resolve_theme(None, "PL", slug) == expected


def test_role_beats_category() -> None:
    # Analityk systemowy w kategorii Infra — dane 12 mies. pokazują, że tak bywa.
    assert (
        ct.resolve_theme(None, "Analityk systemowy", "infrastructure_operations")
        == "jasny"
    )


def test_stored_choice_beats_everything() -> None:
    assert ct.resolve_theme("jasny", "Tester manualny", "security_quality") == "jasny"


@pytest.mark.parametrize("legacy", ["plan", "glitch", "konstelacja", "radar", "papier"])
def test_legacy_scene_choice_falls_back_to_role_default(legacy: str) -> None:
    # Wybory z 12 scen (19–28.10.2026) zostają w bazie, ale strona pokazuje
    # domyślny szablon roli — opublikowane linki dostają nowy wygląd od razu.
    assert (
        ct.resolve_theme(legacy, "PL_EU AMLR Package - KYC delivery lead", None)
        == "jasny"
    )
    assert ct.resolve_theme(legacy, "Senior Java Developer", None) == "terminal"


def test_unknown_stored_value_is_ignored() -> None:
    # Szablon wycofany z listy nie może zostawić strony bez wyglądu.
    assert ct.resolve_theme("nie-ma-takiego", "Java Developer", None) == "terminal"


def test_three_themes_with_polish_labels() -> None:
    assert ct.THEMES == ("grafit", "terminal", "jasny")
    assert ct.DEFAULT_THEME == "grafit"
    assert all(label and label[0].isupper() for label in ct.THEME_LABELS.values())


def test_every_theme_has_a_poster_palette() -> None:
    assert set(ct.POSTER_COLORS) == set(ct.THEMES)
    for colors in ct.POSTER_COLORS.values():
        assert {"bg", "text", "accent", "muted"} <= set(colors)
