"""Fragmenty umowy ramowej klienta — podział, ranking po słowach, wybór.

Czyste funkcje, bez bazy i bez sieci. Zapis, embeddingi i Qdrant są w
``framework_contract_index``.

Umowa ma kilkadziesiąt stron, a wynik narzędzia Jarvisa ok. 6000 znaków, więc
Jarvis dostaje FRAGMENTY: najlepiej pasujące do pytania albo kolejne od podanego
numeru. Fragmenty są ciągłymi wycinkami tekstu (sklejone dają cały tekst), żeby
czytanie po kolei niczego nie powtarzało ani nie gubiło.

Ranking po słowach jest ZAPASEM dla wyszukiwania po znaczeniu: umowy nazywają
rzeczy inaczej niż ludzie (pomiar 09.10.2026: umowa Banku Pocztowego nie zna
frazy „Karta Czasu Pracy”, pisze „Karta Ewidencji Świadczenia Usług”).
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

from app.services.help_search import _STOPWORDS as _HELP_STOPWORDS
from app.services.help_search import fold

# Fragment celuje w tyle znaków; nowy zaczyna się też przy „§”, gdy bieżący ma
# już co najmniej MIN_SECTION_CHARS (inaczej każdy krótki paragraf byłby
# osobnym fragmentem bez kontekstu).
TARGET_CHUNK_CHARS = 800
MIN_SECTION_CHARS = 250
MAX_CHUNK_CHARS = 2 * TARGET_CHUNK_CHARS

# Tyle znaków treści mieści się w jednym wyniku narzędzia Jarvisa
# (``tools.MAX_RESULT_CHARS`` = 6000 razem z opisem umów i znakami JSON-a).
PASSAGE_BUDGET = 4000

_SECTION_LINE = re.compile(r"\s*§")
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = _HELP_STOPWORDS | {"ile", "jaki", "jaka", "jakie", "kiedy", "ma", "sa"}
_MAX_STEMS = 12


@dataclass(frozen=True)
class ChunkRef:
    """Fragment umowy z bazy: ``id`` jest też identyfikatorem punktu w Qdrancie."""

    id: int
    contract_id: int
    index: int
    text: str


@dataclass(frozen=True)
class Passage:
    """Jeden albo kilka sąsiednich fragmentów jednej umowy."""

    contract_id: int
    first_chunk: int
    last_chunk: int
    text: str


def _cut_long(text: str, start: int, end: int) -> list[int]:
    """Granice wewnątrz wycinka dłuższego niż limit — na spacji, gdy się da."""
    cuts: list[int] = []
    while end - start > MAX_CHUNK_CHARS:
        cut = text.rfind(
            " ", start + TARGET_CHUNK_CHARS // 2, start + TARGET_CHUNK_CHARS
        )
        cut = cut + 1 if cut > start else start + TARGET_CHUNK_CHARS
        cuts.append(cut)
        start = cut
    return cuts


def split_into_chunks(text: str) -> list[str]:
    """Ciągłe wycinki tekstu: ``"".join(wynik) == text``."""
    if not text or not text.strip():
        return []
    bounds = [0]
    position = 0
    for line in text.splitlines(keepends=True):
        size = position - bounds[-1]
        if size >= TARGET_CHUNK_CHARS or (
            size >= MIN_SECTION_CHARS and _SECTION_LINE.match(line)
        ):
            bounds.append(position)
        position += len(line)
        bounds.extend(_cut_long(text, bounds[-1], position))
    bounds.append(len(text))

    chunks: list[str] = []
    for start, end in zip(bounds, bounds[1:]):
        piece = text[start:end]
        if not piece:
            continue
        # Sam odstęp nie jest fragmentem — dokleja się do sąsiada.
        if not piece.strip() and chunks:
            chunks[-1] += piece
        elif chunks and not chunks[-1].strip():
            chunks[-1] += piece
        else:
            chunks.append(piece)
    return chunks


def query_stems(query: Optional[str]) -> list[str]:
    """Rdzenie słów pytania: bez polskich znaków, bez słów-wypełniaczy.

    Krótkie słowo traci ostatnią literę („karty” → „kart”, „czasu” → „czas”),
    długie jest cięte do pięciu znaków — zamiast pełnego stemmera.
    """
    stems: list[str] = []
    for token in _TOKEN.findall(fold(query or "")):
        if len(token) < 3 or token in _STOPWORDS:
            continue
        stem = token[: min(5, max(3, len(token) - 1))]
        if stem not in stems:
            stems.append(stem)
    return stems[:_MAX_STEMS]


def rank_by_keywords(stems: Sequence[str], chunks: Sequence[ChunkRef]) -> list[int]:
    """Identyfikatory fragmentów z trafieniem, najlepszy pierwszy.

    Rzadkie słowo waży więcej (IDF liczone na podanych fragmentach): nazwa
    klienta stoi w każdym akapicie umowy i nie może decydować o kolejności.
    """
    if not stems or not chunks:
        return []
    counts: list[dict[str, int]] = []
    for chunk in chunks:
        tokens = _TOKEN.findall(fold(chunk.text))
        counts.append(
            {
                stem: hits
                for stem in stems
                if (hits := sum(1 for token in tokens if token.startswith(stem)))
            }
        )
    total = len(chunks)
    weight = {
        stem: math.log(1 + total / found)
        for stem in stems
        if (found := sum(1 for per_chunk in counts if stem in per_chunk))
    }
    scored = [
        (
            sum(
                weight[stem] * (1 + 0.25 * min(hits - 1, 3))
                for stem, hits in hit.items()
            ),
            chunk,
        )
        for chunk, hit in zip(chunks, counts)
        if hit
    ]
    scored.sort(key=lambda row: (-row[0], row[1].contract_id, row[1].index))
    return [chunk.id for _score, chunk in scored]


def build_passages(
    ranked_ids: Sequence[int],
    chunks: Sequence[ChunkRef],
    *,
    budget: int = PASSAGE_BUDGET,
) -> list[Passage]:
    """Najlepsze fragmenty do limitu znaków; sąsiednie sklejone w jeden.

    Kolejność wyniku idzie za rankingiem (pasaż z najlepszym fragmentem
    pierwszy). Identyfikator spoza ``chunks`` jest pomijany — to punkt Qdranta
    bez wiersza w bazie.
    """
    by_id = {chunk.id: chunk for chunk in chunks}
    picked: list[ChunkRef] = []
    used = 0
    for chunk_id in ranked_ids:
        chunk = by_id.get(chunk_id)
        if chunk is None or chunk in picked:
            continue
        if picked and used + len(chunk.text) > budget:
            continue
        picked.append(chunk)
        used += len(chunk.text)
        if used >= budget:
            break
    if not picked:
        return []

    rank = {chunk.id: position for position, chunk in enumerate(picked)}
    passages: list[tuple[int, Passage]] = []
    for chunk in sorted(picked, key=lambda c: (c.contract_id, c.index)):
        last = passages[-1][1] if passages else None
        if (
            last is not None
            and last.contract_id == chunk.contract_id
            and last.last_chunk + 1 == chunk.index
        ):
            passages[-1] = (
                min(passages[-1][0], rank[chunk.id]),
                Passage(
                    contract_id=last.contract_id,
                    first_chunk=last.first_chunk,
                    last_chunk=chunk.index,
                    text=last.text + chunk.text,
                ),
            )
        else:
            passages.append(
                (
                    rank[chunk.id],
                    Passage(chunk.contract_id, chunk.index, chunk.index, chunk.text),
                )
            )
    passages.sort(key=lambda row: row[0])
    result = [passage for _rank, passage in passages]
    if len(result) == 1 and len(result[0].text) > budget:
        only = result[0]
        result = [
            Passage(
                only.contract_id, only.first_chunk, only.last_chunk, only.text[:budget]
            )
        ]
    return result


def read_in_order(
    chunks: Sequence[ChunkRef],
    *,
    from_chunk: int,
    budget: int = PASSAGE_BUDGET,
) -> tuple[Optional[Passage], Optional[int]]:
    """Kolejne fragmenty jednej umowy od ``from_chunk``; zwraca też numer następnego."""
    ordered = sorted(
        (chunk for chunk in chunks if chunk.index >= from_chunk),
        key=lambda c: c.index,
    )
    if not ordered:
        return None, None
    taken: list[ChunkRef] = []
    used = 0
    for chunk in ordered:
        if taken and used + len(chunk.text) > budget:
            break
        taken.append(chunk)
        used += len(chunk.text)
    passage = Passage(
        contract_id=taken[0].contract_id,
        first_chunk=taken[0].index,
        last_chunk=taken[-1].index,
        text="".join(chunk.text for chunk in taken)[:budget],
    )
    next_chunk = taken[-1].index + 1 if len(taken) < len(ordered) else None
    return passage, next_chunk
