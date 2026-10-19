"""Szablon graficzny strony kariery: rola z tytułu, potem kategoria (19.10.2026).

Decyzja Artura 19.10.2026: domyślny szablon wynika z roli w tytule rekrutacji,
a gdy tytuł nic nie mówi — z kategorii kompetencji. Analitycy systemowi
i testerzy są rozrzuceni po kategoriach (dane z 12 miesięcy), więc sama
kategoria dawałaby analitykowi szablon DevOps.
"""

from __future__ import annotations

import pytest

from app.services import career_theme as ct


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Starszy programista Java", "terminal"),
        ("Senior Java Developer", "terminal"),
        ("Tester automatyzujący", "glitch"),
        ("QA Test Engineer Senior", "glitch"),
        ("Tester manualny", "papier"),
        ("Manual Tester", "papier"),
        ("Analityk systemowy mid", "sekwencja"),
        ("IT Analyst", "sekwencja"),
        ("Analityk biznesowy senior", "tablica"),
        ("Analityk biznesowo-systemowy", "tablica"),
        ("Architekt rozwiązań IT senior", "c4"),
        ("Solution Architect", "c4"),
        ("Kierownik projektu", "plan"),
        ("Scrum Master", "plan"),
        ("PMO Specialist", "plan"),
        ("DevOps Engineer", "topologia"),
        ("Cloud Engineer (Azure)", "topologia"),
        ("Data Engineer", "konstelacja"),
        ("Specjalista ds. hurtowni danych", "konstelacja"),
        ("Security Engineer", "radar"),
        ("Specjalista ds. bezpieczeństwa IT", "radar"),
        ("Administrator systemów Linux", "szafa"),
        ("Frontend Developer", "horyzont"),
        ("Fullstack Developer", "horyzont"),
    ],
)
def test_role_from_title(title: str, expected: str) -> None:
    assert ct.role_theme(title) == expected


@pytest.mark.parametrize(
    "title",
    ["PL", "", "Nordea: PL", "Konsultant GCOP", "On hold"],
)
def test_title_without_a_role_gives_none(title: str) -> None:
    assert ct.role_theme(title) is None


def test_not_every_automation_is_a_tester() -> None:
    # „automatyzacja” bez testów to np. RPA — nie szablon testera.
    assert ct.role_theme("Specjalista ds. automatyzacji procesów") is None


@pytest.mark.parametrize(
    ("slug", "expected"),
    [
        ("software_development", "terminal"),
        ("infrastructure_operations", "topologia"),
        ("security_quality", "glitch"),
        ("management_delivery", "plan"),
        ("data_ai", "konstelacja"),
        (None, "terminal"),
        ("cos_nowego", "terminal"),
    ],
)
def test_category_fallback(slug, expected) -> None:
    assert ct.resolve_theme(None, "PL", slug) == expected


def test_role_beats_category() -> None:
    # Analityk systemowy w kategorii Infra — dane 12 mies. pokazują, że tak bywa.
    assert (
        ct.resolve_theme(None, "Analityk systemowy", "infrastructure_operations")
        == "sekwencja"
    )


def test_stored_choice_beats_everything() -> None:
    assert ct.resolve_theme("radar", "Tester manualny", "security_quality") == "radar"


def test_unknown_stored_value_is_ignored() -> None:
    # Szablon wycofany z listy nie może zostawić strony bez wyglądu.
    assert ct.resolve_theme("nie-ma-takiego", "Java Developer", None) == "terminal"


def test_twelve_themes_with_polish_labels() -> None:
    assert len(ct.THEMES) == 12
    assert ct.DEFAULT_THEME in ct.THEMES
    assert all(label and label[0].isupper() for label in ct.THEME_LABELS.values())
    assert set(ct.THEME_LABELS) == set(ct.THEMES)


def test_every_theme_has_a_poster_palette() -> None:
    assert set(ct.POSTER_COLORS) == set(ct.THEMES)
    for colors in ct.POSTER_COLORS.values():
        assert {"bg", "text", "accent", "muted"} <= set(colors)
