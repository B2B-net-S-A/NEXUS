"""Dwie wersje tekstu → lista zmian silnika.

Wersja pierwotna to akapity DOCX (``read_paragraphs``), nowa — tekst z akapitami
rozdzielonymi znakiem nowego wiersza, a złamaniem wiersza w akapicie jako U+2028 (np. wklejona poprawiona treść albo tekst
po ręcznej edycji w panelu). Akapity porównujemy całe, a w parach zmienionych
akapitów — słowami, żeby zmiana „30 dni” → „14 dni” była jedną małą wstawką,
a nie przepisanym akapitem.
"""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher

from app.services.legal_redline.model import RedlineChange

LINE_BREAK = "\u2028"
_TOKEN = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)
# Akapity podobne co najmniej w tym stopniu traktujemy jako „ten sam, zmieniony”.
_SAME_PARAGRAPH_RATIO = 0.5

# Limity kosztu. ``SequenceMatcher`` na powtarzalnym tekście („a a a …”) jest
# w praktyce sześcienny: 1000 tokenów to ok. 2 s, 8000 — minuty w wątku
# serwera. Ponad limit porównanie słowami obejmuje tylko środek akapitu (bez
# wspólnego początku i końca), a gdy i on jest za długi — środek idzie jako
# jedna zamiana; podobieństwo akapitów liczymy wtedy szacunkiem liniowym.
#: Najwięcej akapitów z każdej strony; ponad to ``DiffTooLarge`` (422).
MAX_PARAGRAPHS = 3000
#: Tokeny (słowa, odstępy, znaki) jednego akapitu porównywane ``SequenceMatcher``.
WORD_DIFF_MAX_TOKENS = 600
#: Łącznie w jednym porównaniu; po wyczerpaniu — zmiany całymi środkami akapitów.
WORD_DIFF_BUDGET = 8_000
#: Znaki pary akapitów, dla której podobieństwo liczy dokładny ``ratio``.
EXACT_RATIO_MAX_CHARS = 300
#: Łącznie znaków w dokładnych ``ratio``; potem już tylko szacunek.
EXACT_RATIO_BUDGET = 60_000
#: Par jednakowych akapitów (stary × nowy) dla dokładnego dopasowania całości;
#: ponad to powtarzalne akapity są dla ``SequenceMatcher`` „popularne” (autojunk).
MAX_EQUAL_PAIRS = 50_000
#: Par akapitów sprawdzanych na „ten sam, zmieniony”; potem reszta bloku to
#: skreślenia i wstawki całych akapitów.
PAIR_CHECKS_BUDGET = 20_000


class DiffTooLarge(ValueError):
    """Tekst za duży do porównania — komunikat dla człowieka."""


class _Budget:
    def __init__(self) -> None:
        self.words = WORD_DIFF_BUDGET
        self.ratio = EXACT_RATIO_BUDGET
        self.pairs = PAIR_CHECKS_BUDGET


def _tokens(text: str) -> list[tuple[str, int]]:
    return [(m.group(), m.start()) for m in _TOKEN.finditer(text)]


def _common_ends(a: list, b: list) -> tuple[int, int]:
    """Długość wspólnego początku i końca (końca bez nakładania na początek)."""
    limit = min(len(a), len(b))
    head = 0
    while head < limit and a[head] == b[head]:
        head += 1
    tail = 0
    while tail < limit - head and a[-1 - tail] == b[-1 - tail]:
        tail += 1
    return head, tail


def _opcodes(a: list[str], b: list[str], budget: _Budget | None) -> list[tuple]:
    if len(a) + len(b) <= WORD_DIFF_MAX_TOKENS and (
        budget is None or budget.words >= len(a) + len(b)
    ):
        if budget is not None:
            budget.words -= len(a) + len(b)
        return SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    head, tail = _common_ends(a, b)
    a_mid, b_mid = a[head : len(a) - tail], b[head : len(b) - tail]
    size = len(a_mid) + len(b_mid)
    if size == 0:
        return []
    if size <= WORD_DIFF_MAX_TOKENS and (budget is None or budget.words >= size):
        if budget is not None:
            budget.words -= size
        return [
            (tag, i1 + head, i2 + head, j1 + head, j2 + head)
            for tag, i1, i2, j1, j2 in SequenceMatcher(
                None, a_mid, b_mid, autojunk=False
            ).get_opcodes()
        ]
    return [("replace", head, len(a) - tail, head, len(b) - tail)]


def _paragraph_matcher(old: list[str], new: list[str]) -> SequenceMatcher:
    """Dopasowanie akapitów; setki jednakowych akapitów (puste wiersze, „x”)
    po obu stronach to przypadek sześcienny — wtedy ``autojunk``."""
    counts = Counter(new)
    equal_pairs = sum(counts.get(text, 0) for text in old)
    return SequenceMatcher(None, old, new, autojunk=equal_pairs > MAX_EQUAL_PAIRS)


def _similarity(a: str, b: str, budget: _Budget) -> float:
    """``SequenceMatcher.ratio`` dla krótkich par, dla długich — szacunek liniowy
    (wspólny początek i koniec + ``quick_ratio`` środka)."""
    budget.pairs -= 1
    if not a and not b:
        return 1.0
    size = len(a) + len(b)
    if size <= EXACT_RATIO_MAX_CHARS and budget.ratio >= size:
        budget.ratio -= size
        return SequenceMatcher(None, a, b, autojunk=False).ratio()
    head, tail = _common_ends(list(a), list(b))
    a_mid, b_mid = a[head : len(a) - tail], b[head : len(b) - tail]
    middle = SequenceMatcher(None, a_mid, b_mid, autojunk=False)
    matches = middle.quick_ratio() * (len(a_mid) + len(b_mid)) / 2
    return 2 * (head + tail + matches) / size


def word_changes(
    old: str, new: str, paragraph: int, prefix: str, budget: _Budget | None = None
) -> list[RedlineChange]:
    """Zmiany w jednym akapicie, słowami; sąsiednie zmiany przedzielone samą spacją łączymy."""

    old_tokens = _tokens(old)
    new_tokens = _tokens(new)
    opcodes = _opcodes([t for t, _ in old_tokens], [t for t, _ in new_tokens], budget)
    spans: list[list[int]] = []  # [old_start, old_end, new_start, new_end]
    for tag, i1, i2, j1, j2 in opcodes:
        if tag == "equal":
            continue
        o_start = old_tokens[i1][1] if i1 < len(old_tokens) else len(old)
        o_end = (
            old_tokens[i2 - 1][1] + len(old_tokens[i2 - 1][0]) if i2 > i1 else o_start
        )
        n_start = new_tokens[j1][1] if j1 < len(new_tokens) else len(new)
        n_end = (
            new_tokens[j2 - 1][1] + len(new_tokens[j2 - 1][0]) if j2 > j1 else n_start
        )
        if spans:
            prev = spans[-1]
            gap_old = old[prev[1] : o_start]
            gap_new = new[prev[3] : n_start]
            if gap_old == gap_new and gap_old.strip() == "" and len(gap_old) <= 1:
                prev[1], prev[3] = o_end, n_end
                continue
        spans.append([o_start, o_end, n_start, n_end])
    return [
        RedlineChange(
            id=f"{prefix}{k + 1}",
            kind="replace",
            paragraph=paragraph,
            start=o_start,
            end=o_end,
            find=old[o_start:o_end],
            new_text=new[n_start:n_end],
        )
        for k, (o_start, o_end, n_start, n_end) in enumerate(spans)
    ]


def diff_texts(old_paragraphs: list[str], new_text: str) -> list[RedlineChange]:
    """Akapity dokumentu i nowa wersja tekstu → zmiany (``replace`` / wstawione / skreślone akapity)."""

    # Złamanie wiersza w akapicie (`w:br`) przychodzi jako U+2028 — tylko
    # prawdziwy koniec wiersza dzieli akapity.
    new_paragraphs = [
        line.replace(LINE_BREAK, "\n")
        for line in new_text.replace("\r\n", "\n").split("\n")
    ]
    if max(len(old_paragraphs), len(new_paragraphs)) > MAX_PARAGRAPHS:
        raise DiffTooLarge(
            f"Tekst ma ponad {MAX_PARAGRAPHS} akapitów — porównaj dokument częściami."
        )
    budget = _Budget()
    matcher = _paragraph_matcher(old_paragraphs, new_paragraphs)
    changes: list[RedlineChange] = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"d{counter}"

    def insert_after(anchor: int, texts: list[str]) -> None:
        for text in texts:
            if not text.strip():
                continue
            if anchor < 0:
                changes.append(
                    RedlineChange(
                        id=next_id(),
                        kind="insert_paragraph",
                        paragraph=0,
                        before=True,
                        new_text=text,
                    )
                )
            else:
                changes.append(
                    RedlineChange(
                        id=next_id(),
                        kind="insert_paragraph",
                        paragraph=anchor,
                        new_text=text,
                    )
                )

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            for i in range(i1, i2):
                if old_paragraphs[i].strip():
                    changes.append(
                        RedlineChange(
                            id=next_id(),
                            kind="delete_paragraph",
                            paragraph=i,
                            find=old_paragraphs[i],
                        )
                    )
            continue
        if tag == "insert":
            insert_after(i1 - 1, new_paragraphs[j1:j2])
            continue
        # replace: pary podobnych akapitów → zmiany słowami, reszta jako całe akapity.
        olds = list(range(i1, i2))
        news = list(range(j1, j2))
        last_old = i1 - 1
        pending_new: list[str] = []
        for j in news:
            match = (
                None
                if budget.pairs <= 0
                else next(
                    (
                        i
                        for i in olds
                        if i > last_old
                        and _similarity(old_paragraphs[i], new_paragraphs[j], budget)
                        >= _SAME_PARAGRAPH_RATIO
                    ),
                    None,
                )
            )
            if match is None:
                pending_new.append(new_paragraphs[j])
                continue
            for i in range(last_old + 1, match):
                if old_paragraphs[i].strip():
                    changes.append(
                        RedlineChange(
                            id=next_id(),
                            kind="delete_paragraph",
                            paragraph=i,
                            find=old_paragraphs[i],
                        )
                    )
            insert_after(match - 1, pending_new)
            pending_new = []
            for change in word_changes(
                old_paragraphs[match],
                new_paragraphs[j],
                match,
                prefix=f"d{counter + 1}.",
                budget=budget,
            ):
                changes.append(change)
            counter += 1
            last_old = match
        for i in range(last_old + 1, i2):
            if old_paragraphs[i].strip():
                changes.append(
                    RedlineChange(
                        id=next_id(),
                        kind="delete_paragraph",
                        paragraph=i,
                        find=old_paragraphs[i],
                    )
                )
        insert_after(i2 - 1 if last_old < i2 - 1 else last_old, pending_new)
    return changes
