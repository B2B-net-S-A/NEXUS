"""Znaki niewidoczne w tekście ogłoszenia.

Tekst wklejony z Worda albo PDF-a niesie miękkie łączniki (U+00AD) i spacje
zerowej szerokości (U+200B). Człowiek ich nie widzi, a nazwa klienta
z miękkim łącznikiem w środku nie jest już dla kontroli nazwą klienta,
tak samo jak „180 zł” ze spacją zerowej szerokości nie jest kwotą.
Dlatego zapis i render je wycinają, a kontrola porównuje tekst sprowadzony
dodatkowo do postaci NFKC („ＰＬＮ” → „PLN”, „＠” → „@”).
"""

from __future__ import annotations

import unicodedata

# Łącznik zerowej szerokości skleja emoji złożone z kilku znaków — w zapisanej
# treści zostaje, kontrola go pomija.
_ZWJ = "\u200d"


def visible(text: str) -> str:
    """Tekst bez znaków formatujących (kategoria Cf), z zachowaniem emoji."""
    return "".join(ch for ch in text if ch == _ZWJ or unicodedata.category(ch) != "Cf")


def for_lint(text: str) -> str:
    """Postać do porównań w kontroli: NFKC i bez żadnego znaku formatującego."""
    return "".join(
        ch
        for ch in unicodedata.normalize("NFKC", text)
        if unicodedata.category(ch) != "Cf"
    )
