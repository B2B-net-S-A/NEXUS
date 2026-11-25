"""Układ tekstu umowy: akapity, zdania, paragrafy (§) i ustępy — czyste funkcje.

Tekst z PDF-u ma złamane wiersze i dzielenie wyrazów, a z OCR dodatkowo
szum. Składamy wiersze w akapity, akapity tniemy na zdania (bez cięcia na
skrótach „np.”, „ust.”, „pkt.”), a każde zdanie zna swój paragraf, ustęp
i przesunięcie w całym tekście dokumentu — z tego powstaje odnośnik
„§ 12 ust. 2” przy cytacie.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

from app.services.help_search import fold

_SECTION = re.compile(r"^\s*§\s*(\d+[A-Za-z]?)")
_POINT = re.compile(r"^\s*(\d{1,2})\s*[.)]\s+\S")
_STARTS_NEW = re.compile(r"^\s*(§|\d{1,2}\s*[.)]\s|[a-z]\)\s|[•·▪\-–]\s)")
_ABBREVIATIONS = frozenset(
    {
        "np",
        "ust",
        "pkt",
        "art",
        "nr",
        "tj",
        "ok",
        "in",
        "itd",
        "itp",
        "zl",
        "r",
        "poz",
        "lit",
        "str",
        "tel",
        "godz",
        "al",
        "ul",
        "sp",
        "o",
        "z",
        "tzw",
        "dot",
        "zob",
        "par",
        "dz",
        "u",
    }
)
_SENTENCE_END = re.compile(r"[.!?;]\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ„\"(•])")


@dataclass(frozen=True)
class Sentence:
    """Zdanie z oryginalną pisownią, jego paragraf, ustęp i miejsce w tekście."""

    text: str
    folded: str
    section: Optional[str]
    point: Optional[str]
    offset: int
    paragraph: int


@dataclass(frozen=True)
class Marker:
    """Początek paragrafu albo ustępu w tekście dokumentu."""

    offset: int
    section: Optional[str]
    point: Optional[str]


def _paragraphs(text: str) -> list[tuple[int, str]]:
    """Akapity: (przesunięcie początku, tekst ze złożonymi wierszami)."""
    out: list[tuple[int, str]] = []
    current: list[str] = []
    start = 0
    position = 0

    def flush() -> None:
        if current:
            joined = ""
            for line in current:
                if not joined:
                    joined = line
                elif joined.endswith("-") and line[:1].islower():
                    joined = joined[:-1] + line
                else:
                    joined = f"{joined} {line}"
            out.append((start, joined))
            current.clear()

    for raw in text.splitlines(keepends=True):
        line = raw.strip()
        if not line:
            flush()
        else:
            if current and _STARTS_NEW.match(line):
                flush()
            if not current:
                start = position + (len(raw) - len(raw.lstrip()))
            # Nagłówek „§ 12” zaczyna nowy akapit i sam nim jest — tytuł
            # paragrafu („Rozwiązanie umowy”) nie skleja się z ust. 1.
            current.append(line)
            if _SECTION.match(line) and len(line) < 40:
                flush()
        position += len(raw)
    flush()
    return out


def _split_sentences(paragraph: str) -> list[tuple[int, str]]:
    pieces: list[tuple[int, str]] = []
    last = 0
    for match in _SENTENCE_END.finditer(paragraph):
        before = paragraph[last : match.start()]
        word = re.findall(r"([A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+)$", before)
        if paragraph[match.start()] == "." and word and fold(word[0]) in _ABBREVIATIONS:
            continue
        pieces.append((last, paragraph[last : match.start() + 1].strip()))
        last = match.end()
    tail = paragraph[last:].strip()
    if tail:
        pieces.append((last, tail))
    return [(offset, text) for offset, text in pieces if text]


def sentences(text: str) -> list[Sentence]:
    """Zdania dokumentu w kolejności, z paragrafem i ustępem, w którym stoją."""
    out: list[Sentence] = []
    section: Optional[str] = None
    point: Optional[str] = None
    for index, (offset, paragraph) in enumerate(_paragraphs(text)):
        heading = _SECTION.match(paragraph)
        if heading:
            section, point = heading.group(1), None
        else:
            numbered = _POINT.match(paragraph)
            if numbered:
                point = numbered.group(1)
        for local, sentence in _split_sentences(paragraph):
            out.append(
                Sentence(
                    text=sentence,
                    folded=fold(sentence),
                    section=section,
                    point=point,
                    # Przesunięcie początku akapitu w tekście, plus miejsce
                    # w akapicie (po złożeniu wierszy przybliżone).
                    offset=offset + local,
                    paragraph=index,
                )
            )
    return out


def markers(text: str) -> list[Marker]:
    """Początki paragrafów i ustępów — do odnośnika przy dowolnym fragmencie."""
    out: list[Marker] = []
    section: Optional[str] = None
    for offset, paragraph in _paragraphs(text):
        heading = _SECTION.match(paragraph)
        if heading:
            section = heading.group(1)
            out.append(Marker(offset, section, None))
            continue
        numbered = _POINT.match(paragraph)
        if numbered and section is not None:
            out.append(Marker(offset, section, numbered.group(1)))
    return out


def ref_of(section: Optional[str], point: Optional[str]) -> Optional[str]:
    if section is None:
        return None
    return f"§ {section} ust. {point}" if point else f"§ {section}"


def range_ref(found: Sequence[Marker], start: int, end: int) -> Optional[str]:
    """Odnośnik do wycinka ``[start, end)``: „§ 12 ust. 2” albo „§ 12–13”."""
    if not found:
        return None
    offsets = [m.offset for m in found]
    first_at = bisect_right(offsets, start) - 1
    inside = [m for m in found if start < m.offset < end]
    first = found[first_at] if first_at >= 0 else (inside[0] if inside else None)
    if first is None:
        return None
    sections = [first.section] + [
        m.section for m in inside if m.section != first.section
    ]
    distinct = list(dict.fromkeys(s for s in sections if s))
    if len(distinct) > 1:
        return f"§ {distinct[0]}–{distinct[-1]}"
    points = {m.point for m in inside if m.section == first.section}
    if points - {first.point}:
        return ref_of(first.section, None)
    return ref_of(first.section, first.point)


_NUMBER = re.compile(
    r"\b(?:umow\w*|aneks\w*|porozumieni\w*|wypowiedzeni\w*)"
    r"(?:\s+(?!nr\b|numer\b)[^\s\d]+){0,4}?\s+(?:nr|numer)\.?\s*"
    r"([A-Z0-9][\w/.\-]*\d[\w/\-]*)",
    re.IGNORECASE,
)


def document_number(text: str) -> Optional[str]:
    """Numer z nagłówka dokumentu („Umowa nr 12/2025”), gdy stoi na początku."""
    match = _NUMBER.search(text[:1500])
    return match.group(1).rstrip(".,") if match else None
