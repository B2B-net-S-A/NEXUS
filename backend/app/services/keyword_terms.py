"""Słowa kluczowe listy kandydatów: CAŁE SŁOWA, gwiazdka i zakres pola.

Decyzja Artura (22.09.2026, porównanie z Traffitem): „java” ma znaleźć osobę
znającą Javę, a nie JavaScript. Do tej daty słowo kluczowe było podłańcuchem
albo prefiksem słowa (``java:*``), więc na produkcji „java” dawało 22 384 osoby
— w tym ~8 tys. programistów JavaScript — a Traffit 15 916.

Reguły (tylko semantyka v2 listy i wyszukiwarki; v1 zostaje nietknięta, na niej
stoją alerty zapisanych wyszukiwań):

* ``java``     — całe słowo: „Java”, „Java 17”, „Java, Spring” — nie „JavaScript”.
* ``java*``    — początek słowa: „Java”, „JavaScript”, „Java8”.
* ``*script``  — koniec słowa: „JavaScript”, „TypeScript”.
* ``bankow*``  — odmiana: „bankowość”, „bankowego”, „bankowym”.
* ``spring boot`` — fraza: słowa obok siebie, w tej kolejności.
* ``c++``, ``.net``, ``node.js`` — dosłownie; granica słowa tylko po stronie
  litery/cyfry (``c++`` znajduje „C++17”, ``.net`` znajduje „ASP.NET”).

Granica słowa: znak, który NIE jest literą/cyfrą/podkreśleniem. Postgres na
produkcji ma ctype ``C`` (musl), więc ``[[:alnum:]]`` zna tylko ASCII — polskie,
niemieckie i cyrylickie litery dopisujemy jawnie, inaczej „zażółć” miałoby
granicę słowa w środku. Ta sama klasa jest w ``WORD_CHARS_PY`` (wycinki) i we
froncie (``lib/keyword-terms.ts``) — trzy lustra jednej reguły.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal, Optional

KeywordScope = Literal["all", "cv", "title", "skills", "notes"]
KEYWORD_SCOPES: tuple[str, ...] = ("all", "cv", "title", "skills", "notes")

# Litery spoza ASCII traktowane jako część słowa: Latin-1 (bez × i ÷),
# Latin Extended-A (polskie, czeskie, niemieckie…) i cyrylica.
_EXTRA_WORD_RANGES = "À-ÖØ-öø-ÿĀ-žЀ-ӿ"
WORD_CLASS_PG = f"[:alnum:]_{_EXTRA_WORD_RANGES}"
WORD_CHARS_PY = f"0-9A-Za-z_{_EXTRA_WORD_RANGES}"

_LEFT_PG = f"(^|[^{WORD_CLASS_PG}])"
_RIGHT_PG = f"($|[^{WORD_CLASS_PG}])"
_LEFT_PY = f"(?<![{WORD_CHARS_PY}])"
_RIGHT_PY = f"(?![{WORD_CHARS_PY}])"

_PHRASE_GAP_PG = "[[:space:]/-]+"
_PHRASE_GAP_PY = r"[\s/-]+"

# Znaki specjalne wyrażeń regularnych Postgresa (ARE) i Pythona.
_REGEX_SPECIAL = set("\\^$.|?*+()[]{}")


@dataclass(frozen=True)
class KeywordTerm:
    """Jedno słowo kluczowe po rozbiorze gwiazdek."""

    raw: str
    text: str
    # `java*` — dowolna końcówka słowa; `*script` — dowolny początek.
    open_end: bool = False
    open_start: bool = False

    @property
    def words(self) -> list[str]:
        return self.text.split()

    @property
    def is_plain_word(self) -> bool:
        """Jedno słowo z samych liter/cyfr — idzie przez indeks pełnotekstowy."""
        return len(self.words) == 1 and self.text.isalnum()

    @property
    def is_plain_phrase(self) -> bool:
        """Kilka słów z samych liter/cyfr — fraza pełnotekstowa (`a <-> b`)."""
        words = self.words
        return len(words) > 1 and all(w.isalnum() for w in words)


# Gwiazdka przy krótszym rdzeniu (`*a`, `go*`) zamieniałaby regex w skan
# każdego CV (indeks trigramowy nie ma z czego wyciągnąć trigramów) — przy
# rdzeniu krótszym niż 3 znaki gwiazdka jest ignorowana (całe słowo).
MIN_WILDCARD_CORE = 3


def parse_keyword(raw: str) -> Optional[KeywordTerm]:
    """``"java*"`` → ``KeywordTerm("java", open_end=True)``; pusty → ``None``."""
    value = " ".join(unicodedata.normalize("NFC", raw or "").split())
    open_start = value.startswith("*")
    open_end = value.endswith("*")
    text = value.strip("*").strip()
    if not text:
        return None
    if len(text) < MIN_WILDCARD_CORE:
        open_start = open_end = False
    return KeywordTerm(raw=value, text=text, open_end=open_end, open_start=open_start)


def _escape_char(ch: str) -> str:
    return "\\" + ch if ch in _REGEX_SPECIAL else ch


def _core_pg(text: str) -> str:
    """Rdzeń wzorca: znaki dosłownie, spacje = dowolny odstęp.

    `~*` na produkcji porównuje polskie litery bez wielkości liter
    (sprawdzone: 'Łódź' ~* 'łódź'), więc klasy [łŁ] nie są potrzebne.
    """
    parts = []
    for word in text.split():
        parts.append("".join(_escape_char(ch) for ch in word))
    # Fraza: słowa rozdzielone odstępem, myślnikiem albo ukośnikiem — tak jak
    # `spring <-> boot` z indeksu pełnotekstowego łapie „Spring-Boot”.
    return _PHRASE_GAP_PG.join(parts)


def _is_word_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


def _needs_left(term: KeywordTerm) -> bool:
    """Granica z lewej tylko, gdy słowo zaczyna się literą/cyfrą: `.net` ma
    znaleźć „ASP.NET”, a `java` nie ma znaleźć „JavaScript”."""
    return not term.open_start and _is_word_char(term.text[0])


def _needs_right(term: KeywordTerm) -> bool:
    """Granica z prawej tylko, gdy słowo kończy się literą/cyfrą: `c++` ma
    znaleźć „C++17”."""
    return not term.open_end and _is_word_char(term.text[-1])


def pg_regex(term: KeywordTerm) -> str:
    """Wzorzec POSIX (Postgres ARE) do ``~*`` z granicami słowa."""
    left = _LEFT_PG if _needs_left(term) else ""
    right = _RIGHT_PG if _needs_right(term) else ""
    return f"{left}{_core_pg(term.text)}{right}"


def py_regex(term: KeywordTerm) -> re.Pattern[str]:
    """Ten sam wzorzec w Pythonie — do wycinków pod wynikiem."""
    core = _PHRASE_GAP_PY.join(re.escape(w) for w in term.text.split())
    # Gwiazdka: podświetlamy całe słowo („JavaScript” dla `java*`), nie kawałek.
    if term.open_start:
        prefix = f"[{WORD_CHARS_PY}]*"
    else:
        prefix = _LEFT_PY if _needs_left(term) else ""
    if term.open_end:
        suffix = f"[{WORD_CHARS_PY}]*"
    else:
        suffix = _RIGHT_PY if _needs_right(term) else ""
    return re.compile(f"{prefix}{core}{suffix}", re.IGNORECASE)


def tsquery_path_variants(term: KeywordTerm) -> Optional[str]:
    """Dodatek do całego słowa: prefiksy ``'java/':* | 'java-':*``.

    Parser tsvector trzyma „Java/Spring” jako JEDEN token ``java/spring``
    (ścieżka), więc samo ``java`` go nie znajdzie, a ``java:*`` łapie też
    JavaScript. Ten tekst jest RZUTOWANY (``::tsquery``), nie parsowany — tylko
    tak ukośnik zostaje w leksemie. Małe litery ASCII: wariant dotyczy słów
    technicznych; słowo z polskimi literami i tak łapie ``to_tsquery``.
    Zmierzone na produkcji 22.09.2026: „java” 13 920 osób zamiast 13 877, 48 ms.
    """
    if not term.is_plain_word or term.open_end or term.open_start:
        return None
    word = term.text.lower()
    if not word.isascii():
        return None
    return f"'{word}/':* | '{word}-':*"


def tsquery_text(term: KeywordTerm) -> Optional[str]:
    """Zapytanie ``to_tsquery('simple', …)`` albo ``None`` (regex zamiast FTS).

    Całe słowo → ``java`` (+ ``tsquery_path_variants``), początek słowa →
    ``java:*``, fraza → ``spring <-> boot``. Gwiazdka z przodu nie ma
    odpowiednika w tsquery — wtedy regex. Tekst jest alfanumeryczny, więc nie
    da się nim wstrzyknąć operatora.
    """
    if term.open_start:
        return None
    if term.is_plain_word:
        return term.text + (":*" if term.open_end else "")
    if term.is_plain_phrase:
        words = list(term.words)
        if term.open_end:
            words[-1] = words[-1] + ":*"
        return " <-> ".join(words)
    return None
