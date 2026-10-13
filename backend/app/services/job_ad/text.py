"""Znaki niewidoczne w zapisanej treści ogłoszenia.

Tekst wklejony z Worda albo PDF-a niesie miękkie łączniki (U+00AD) i spacje
zerowej szerokości (U+200B). Zapis i render je wycinają, żeby nie trafiały
na portal. Porównywanie tekstu w kontroli robi ``public_profile_lint.for_lint``
(NFKC i bez żadnego znaku formatującego) — wspólnie ze stroną kariery.

Od 14.10.2026 tej samej funkcji używa zapis opisu na stronie kariery
(``api/career_links.put_public_profile``): znak odwrócenia kierunku (U+202E)
pokazuje „łz 081” jako „180 zł”, a kontrola, która go pomija, widziała
tylko „łz 081”. Tekst bez znaków formatujących wygląda tak, jak go czyta
kontrola.
"""

from __future__ import annotations

import unicodedata

# Łącznik zerowej szerokości skleja emoji złożone z kilku znaków — w zapisanej
# treści zostaje, kontrola go pomija.
_ZWJ = "\u200d"


def visible(text: str) -> str:
    """Tekst bez znaków formatujących (kategoria Cf), z zachowaniem emoji."""
    return "".join(ch for ch in text if ch == _ZWJ or unicodedata.category(ch) != "Cf")
