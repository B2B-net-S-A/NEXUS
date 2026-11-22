"""Czyste funkcje tekstu: pozycje umiejętności, słowa kluczowe, pogrubienia."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Iterable, Pattern, Sequence

esc = html.escape


def clean(text: str) -> str:
    """Bez spacji na brzegach i bez kropki, przecinka, średnika na końcu."""
    return (text or "").strip().rstrip(".,;")


def split_items(content: str) -> list[str]:
    """Lista po przecinkach, ale nie w nawiasach: „Java (Spring, JPA), SQL” → 2 pozycje."""
    out: list[str] = []
    depth, cur = 0, ""
    for ch in (content or "").rstrip(" .,"):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            if cur.strip():
                out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


# narzędnik / dopełniacz: ciąg dalszy wyliczenia („zarządzanie zakresem, ryzykiem”)
_OBLIQUE = ("ami", "iem", "ów", "ji", "ych", "ich", "ości", "ymi", "imi")
# sam przymiotnik: „testy funkcjonalne, regresyjne”
_ADJ = ("ne", "we", "ny", "wy")
_NOT_CONTINUATION = {"dane", "nowe", "wymagania"}


def merge_fragments(items: Sequence[str]) -> list[str]:
    """Pozycja z małej litery, która jest ciągiem dalszym poprzedniej (odmieniony
    rzeczownik albo sam przymiotnik), dokleja się przecinkiem do poprzedniej."""
    out: list[str] = []
    for item in items:
        words = item.split()
        first = words[0] if words else ""
        low = first.lower()
        continuation = (
            out
            and first[:1].islower()
            and low not in _NOT_CONTINUATION
            and len(out[-1].split()) >= 2
            and (low.endswith(_OBLIQUE) or (low.endswith(_ADJ) and len(words) <= 3))
        )
        if continuation:
            out[-1] = f"{out[-1]}, {item}"
        else:
            out.append(item)
    return out


def md_bold(text: str) -> str:
    """`**…**` z generatora jako pogrubienie; reszta zescapowana."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(text or ""))


def strip_md(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")


@dataclass(frozen=True)
class Keywords:
    """Słowa kluczowe rekrutacji: krótkie (do 2 słów) jako całe pozycje i wzorce
    pogrubień z pliku Word (`docx_renderer.compile_keyword_patterns`)."""

    short: frozenset[str]
    patterns: tuple[Pattern[str], ...]

    @classmethod
    def build(cls, keywords: Iterable[str]) -> "Keywords":
        words = [k for k in keywords if k and k.strip()]
        short = frozenset(k.strip().lower() for k in words if len(k.split()) <= 2)
        return cls(short=short, patterns=tuple(_word_patterns(words)))

    def spans(self, text: str) -> list[tuple[int, int]]:
        if not self.patterns or not text:
            return []
        from app.services.cv_generator_b2b.docx_renderer import highlight_spans

        return highlight_spans(text, list(self.patterns))

    def is_key(self, item: str) -> bool:
        """Cała pozycja jest słowem z rekrutacji (dokładnie albo w całości pogrubiona)."""
        item = (item or "").strip()
        if not item:
            return False
        if item.lower() in self.short:
            return True
        return any(s == 0 and e == len(item) for s, e in self.spans(item))

    def bold(self, text: str) -> str:
        """Tekst zescapowany, słowa kluczowe w `<b>` — te same co w pliku Word."""
        spans = self.spans(text or "")
        out, cursor = [], 0
        for start, end in spans:
            out.append(esc(text[cursor:start]))
            out.append(f"<b>{esc(text[start:end])}</b>")
            cursor = end
        out.append(esc((text or "")[cursor:]))
        return "".join(out)


def _word_patterns(keywords: list[str]) -> list[Pattern[str]]:
    if not keywords:
        return []
    from app.services.cv_generator_b2b.docx_renderer import compile_keyword_patterns

    return compile_keyword_patterns(keywords)


def key_first(items: Sequence[str], keys: Keywords) -> list[str]:
    """Najpierw pozycje z rekrutacji, potem reszta — kolejność w grupach jak w CV."""
    return [i for i in items if keys.is_key(i)] + [
        i for i in items if not keys.is_key(i)
    ]
