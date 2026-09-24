"""Napis wymogu Wyścigu Rekomendacji odmienia liczebnik (audyt 24.09.2026).

Do 24.09.2026 ekran mówił „Wymóg: min. 4 weryfikacji/dzień” przy każdej
liczbie. Sam napis — reguła kwalifikacji i ranking są bez zmian.
"""

from __future__ import annotations

import pytest

from app.services.competitions import _verifications_word


@pytest.mark.parametrize(
    ("count", "word"),
    [
        (1, "weryfikacja"),
        (2, "weryfikacje"),
        (4, "weryfikacje"),
        (5, "weryfikacji"),
        (12, "weryfikacji"),
        (14, "weryfikacji"),
        (22, "weryfikacje"),
        (25, "weryfikacji"),
    ],
)
def test_verifications_word_follows_polish_plural(count: int, word: str) -> None:
    assert _verifications_word(count) == word
