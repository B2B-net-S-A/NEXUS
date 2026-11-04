"""Technologia z odczytu CV musi mieć ślad w tekście tego CV.

Audyt modeli z 02.11.2026: parser dopisywał od 0,16 (Sonnet 5) do 0,35 (Haiku 5.5)
technologii na CV, których w dokumencie nie ma. Taka pozycja trafia do profilu
i podnosi osobę w wyszukiwaniu po umiejętności, więc odrzucamy ją przed zapisem,
tak jak `_drop_ungrounded_rate` robi to ze stawką z notatek.

Sprawdzenie jest celowo łagodne: wystarczy jedno znaczące słowo nazwy, alias
z taksonomii albo bliska pisownia, bo „MS Excel” → „Microsoft Excel”, „JS” →
„JavaScript” czy literówka w CV to ta sama technologia, a nie zmyślenie.
"""

from __future__ import annotations

import difflib
import logging
import re
import unicodedata
from typing import Any

from app.services.scoring_service import ALIAS_MAP, skill_name_variants

logger = logging.getLogger(__name__)

_TOKEN = re.compile(r"[a-z0-9+#.]+")
_NOT_NAME_CHAR = re.compile(r"[^a-z0-9+#]")
_GENERIC_WORDS = frozenset(
    "microsoft ms apache google amazon oracle ibm sap framework frameworks library "
    "development developer services service platform cloud tools tool basics basic "
    "advanced authentication authorization management server database db api apis "
    "testing tests language programming web application applications system systems "
    "data and i oraz the of for z w".split()
)
# Czego nie ma w taksonomii, a na próbie 96 CV wyglądało jak zmyślenie.
_MORE_SPELLINGS = {
    "javascript": ("js",),
    "typescript": ("ts",),
    "git": ("github", "gitlab", "bitbucket"),
}
_CLOSE_SPELLING = 0.85


def _fold(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(ascii_text.lower().split())


def _word_in_tokens(word: str, tokens: set[str]) -> bool:
    """Polska odmiana zmienia końcówki, więc długie słowa porównujemy początkiem."""
    if len(word) <= 3:
        return word in tokens
    prefix = word[: max(4, len(word) - 3)]
    if any(token.startswith(prefix) for token in tokens):
        return True
    # Literówka w CV („ArhUnit”): model poprawił nazwę, nie wymyślił technologii.
    return len(word) >= 6 and bool(
        difflib.get_close_matches(word, tokens, n=1, cutoff=_CLOSE_SPELLING)
    )


def _name_in_text(name: str, text: str, tokens: set[str], squashed: str) -> bool:
    needle = _fold(name)
    if not needle:
        return True
    squashed_needle = _NOT_NAME_CHAR.sub("", needle)
    # „Go” i „R” siedzą w każdym tekście jako fragment słowa.
    if len(squashed_needle) <= 3:
        left = r"(?<![a-z0-9])" if needle[0].isalnum() else ""
        right = r"(?![a-z])" if needle[-1].isalnum() else ""
        return re.search(left + re.escape(needle) + right, text) is not None
    if needle in text or squashed_needle in squashed:
        return True
    words = [
        word
        for word in _TOKEN.findall(needle)
        if word not in _GENERIC_WORDS and len(word) >= 2
    ]
    # Sama ogólna nazwa („Cloud”, „Microsoft”) nie daje czego szukać.
    return not words or any(
        _word_in_tokens(word, tokens) or (len(word) > 3 and word in squashed)
        for word in words
    )


def drop_untraced_technologies(parsed: dict[str, Any], cv_text: str) -> int:
    """Usuń z odczytu technologie bez śladu w CV i zwróć, ile ich było.

    Bez mapy aliasów (skrypt, który nie wywołał `refresh_alias_map`) nic nie
    usuwamy, bo „JS” zniknąłby wtedy jako rzekomo zmyślony JavaScript.
    """
    text = _fold(cv_text or "")
    if not text or not ALIAS_MAP:
        return 0
    tokens = set(_TOKEN.findall(text))
    squashed = _NOT_NAME_CHAR.sub("", text)
    verdicts: dict[str, bool] = {}

    def keep(name: Any) -> bool:
        if not isinstance(name, str):
            return True
        if name not in verdicts:
            variants = [
                *(skill_name_variants([name]) or [name]),
                *_MORE_SPELLINGS.get(_fold(name), ()),
            ]
            verdicts[name] = any(
                _name_in_text(variant, text, tokens, squashed) for variant in variants
            )
        return verdicts[name]

    def filter_names(values: Any) -> Any:
        if not isinstance(values, list):
            return values
        return [
            item
            for item in values
            if keep(item.get("name") if isinstance(item, dict) else item)
        ]

    for key in ("skills", "technologies"):
        if key in parsed:
            parsed[key] = filter_names(parsed[key])
    for key in ("experience", "projects"):
        entries = parsed.get(key)
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and "technologies" in entry:
                    entry["technologies"] = filter_names(entry["technologies"])
    dropped = sum(1 for kept in verdicts.values() if not kept)
    if dropped:
        logger.info("[cv_parser] odrzucone technologie bez śladu w CV: %d", dropped)
    return dropped
