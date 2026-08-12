"""Dzielenie tekstu CV na pasaże — Fala 2.

DLACZEGO W OGÓLE. Dzisiejszy retrieval wkłada CAŁE CV w jeden uśredniony wektor,
a wcześniej ucina je do 3 000 znaków. Mediana CV w bazie to 3 556 znaków, p90 to
7 322 — czyli **63% CV jest przycinanych**, a to, co zostaje, miesza dziesięć lat
i pięć ról w jeden punkt. Baseline z 2026-08-10 pokazał, że wąskim gardłem jest
retrieval, nie ranking: przy puli 200 scoring nie widzi 86,4% właściwych osób.

CO TU JEST, A CZEGO NIE MA. Ten moduł wyłącznie TNIE tekst — nie liczy
embeddingów, nie dotyka Qdranta i niczego nie zapisuje. Dzięki temu da się
zmierzyć rozmiar przyszłej kolekcji (liczba pasaży × 1024 wymiary) BEZ płacenia
za embeddingi i bez ruszania produkcji, a to jest warunek wstępny całej fali:
kontener Qdranta ma twardy limit 2 GB RAM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Cel ~1 000 znaków: przy medianie 3 556 daje ~4 pasaże, przy p90 7 322 — ~8.
# Krótsze pasaże to więcej punktów (pamięć), dłuższe wracają do uśredniania,
# przed którym cała ta zmiana ma bronić.
TARGET_CHARS = 1000
MAX_CHARS = 1400

# Zakładka między pasażami: zdanie opisujące rolę bywa przecięte na granicy,
# a bez zakładki żaden z dwóch sąsiadów nie niesie go w całości.
OVERLAP_CHARS = 150

# Pasaż krótszy niż to nie niesie sygnału wartego osobnego punktu w indeksie —
# „Wykształcenie" albo sam nagłówek sekcji zwracałyby losowe dopasowania.
MIN_CHARS = 120

_PARAGRAPH = re.compile(r"\n\s*\n+")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Passage:
    """Jeden pasaż CV wraz z pozycją w tekście źródłowym.

    `index` jest częścią tożsamości punktu w Qdrancie — pozwala nadpisać ten sam
    pasaż przy ponownym przetworzeniu tego samego CV, zamiast mnożyć duplikaty.

    `start`/`end` są PRZYBLIŻONE i służą tylko orientacji. Scalanie bloków
    skleja je pojedynczym `\n`, podczas gdy w źródle rozdzielał je co najmniej
    podwójny — więc `end` potrafi zaniżać pozycję o długość zjedzonych
    separatorów, a każdy kolejny pasaż dziedziczy to przesunięcie. Nic w
    indeksie z nich nie korzysta (payload niesie tekst i indeks, nie offsety);
    NIE nadają się do wycinania podciągów ze źródła.
    """

    index: int
    text: str
    start: int
    end: int


def _split_long_block(block: str) -> list[str]:
    """Potnij zbyt długi akapit po zdaniach, a w ostateczności twardo.

    Twarde cięcie jest ostatecznością, ale MUSI istnieć: CV bywają jednym
    blokiem bez interpunkcji (efekt OCR albo eksportu z PDF-a), a bez tej gałęzi
    taki tekst wracałby jako jeden pasaż wielkości całego dokumentu — czyli
    dokładnie to, czego ta zmiana ma unikać.
    """

    if len(block) <= MAX_CHARS:
        return [block]

    out: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(block):
        if not sentence:
            continue
        if current and len(current) + len(sentence) + 1 > TARGET_CHARS:
            out.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        out.append(current)

    hard: list[str] = []
    for piece in out:
        while len(piece) > MAX_CHARS:
            hard.append(piece[:TARGET_CHARS])
            piece = piece[TARGET_CHARS:]
        if piece:
            hard.append(piece)
    return hard


def split_cv_into_passages(cv_text: str | None) -> list[Passage]:
    """Podziel CV na pasaże po akapitach, z zakładką.

    Deterministyczne: ten sam tekst zawsze daje te same pasaże z tymi samymi
    indeksami. To nie jest kosmetyka — na tym opiera się nadpisywanie punktów
    w Qdrancie zamiast mnożenia duplikatów przy każdym ponownym przebiegu.
    """

    if not cv_text or not cv_text.strip():
        return []

    normalized = cv_text.replace("\r\n", "\n").replace("\r", "\n")

    blocks: list[str] = []
    for raw_block in _PARAGRAPH.split(normalized):
        stripped = raw_block.strip()
        if stripped:
            blocks.extend(_split_long_block(stripped))

    # Sklejaj drobne bloki, póki mieszczą się w celu — inaczej CV zapisane jako
    # lista jednolinijkowych punktów rozpadłoby się na dziesiątki mikropasaży.
    merged: list[str] = []
    for block in blocks:
        if merged and len(merged[-1]) + len(block) + 1 <= TARGET_CHARS:
            merged[-1] = f"{merged[-1]}\n{block}"
        else:
            merged.append(block)

    passages: list[Passage] = []
    cursor = 0
    for position, body in enumerate(merged):
        start = normalized.find(body[:60], cursor) if body else -1
        if start < 0:
            start = cursor
        cursor = start + len(body)

        if position > 0 and OVERLAP_CHARS:
            tail = merged[position - 1][-OVERLAP_CHARS:]
            body = f"{tail}\n{body}"

        if len(body.strip()) < MIN_CHARS and passages:
            # Ogon za krótki na własny punkt — doklej do poprzedniego, zamiast
            # zostawiać w indeksie pasaż, który dopasowuje się do wszystkiego.
            previous = passages.pop()
            passages.append(
                Passage(
                    index=previous.index,
                    text=f"{previous.text}\n{body}".strip(),
                    start=previous.start,
                    end=cursor,
                )
            )
            continue

        if len(body.strip()) < MIN_CHARS:
            continue

        passages.append(
            Passage(index=len(passages), text=body.strip(), start=start, end=cursor)
        )

    return passages


def estimate_passage_count(cv_text: str | None) -> int:
    """Ile punktów w indeksie zajmie to CV — bez liczenia embeddingów."""

    return len(split_cv_into_passages(cv_text))
