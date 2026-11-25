"""Wspólna lista słów „do dziś” w datach stanowisk (zgłoszenie 25.11.2026)."""

import re

import pytest

from app.services.cv_ongoing import ONGOING, ONGOING_WORDS

WORDS = [
    "obecnie", "aktualnie", "teraz", "nadal", "dziś", "dzis", "dzisiaj",
    "do dziś", "do dzisiaj", "do teraz", "present", "Present", "current",
    "currently", "CURRENTLY", "now", "today", "ongoing", "to date", "till date",
    "till now", "until now",
]


@pytest.mark.parametrize("word", WORDS)
def test_every_word_ends_a_range(word: str) -> None:
    assert re.fullmatch(ONGOING_WORDS, word, re.IGNORECASE)
    assert ONGOING.search(f"03.2023 – {word}")


@pytest.mark.parametrize("text", ["Snowflake 2021", "presentation", "known issues"])
def test_word_inside_another_word_is_not_ongoing(text: str) -> None:
    assert ONGOING.search(text) is None


def test_backend_list_covers_the_editor_list() -> None:
    # `PRESENT` w edytorze Nowego CV; backend musi rozpoznać co najmniej to samo.
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "frontend/src/lib/cv-new-layout-form.ts"
    )
    if not source.exists():
        pytest.skip("bez katalogu frontend")
    match = re.search(r"const PRESENT = /\\b\(\?:([^)]*)\)", source.read_text())
    assert match is not None
    for word in match.group(1).split("|"):
        assert re.fullmatch(ONGOING_WORDS, word, re.IGNORECASE), word
