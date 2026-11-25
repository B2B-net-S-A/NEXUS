"""Dwie wersje tekstu → lista zmian silnika.

Wersja pierwotna to akapity DOCX (``read_paragraphs``), nowa — tekst z akapitami
rozdzielonymi znakiem nowego wiersza, a złamaniem wiersza w akapicie jako U+2028 (np. wklejona poprawiona treść albo tekst
po ręcznej edycji w panelu). Akapity porównujemy całe, a w parach zmienionych
akapitów — słowami, żeby zmiana „30 dni” → „14 dni” była jedną małą wstawką,
a nie przepisanym akapitem.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.services.legal_redline.model import RedlineChange

LINE_BREAK = "\u2028"
_TOKEN = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)
# Akapity podobne co najmniej w tym stopniu traktujemy jako „ten sam, zmieniony”.
_SAME_PARAGRAPH_RATIO = 0.5


def _tokens(text: str) -> list[tuple[str, int]]:
    return [(m.group(), m.start()) for m in _TOKEN.finditer(text)]


def word_changes(
    old: str, new: str, paragraph: int, prefix: str
) -> list[RedlineChange]:
    """Zmiany w jednym akapicie, słowami; sąsiednie zmiany przedzielone samą spacją łączymy."""

    old_tokens = _tokens(old)
    new_tokens = _tokens(new)
    matcher = SequenceMatcher(
        None, [t for t, _ in old_tokens], [t for t, _ in new_tokens], autojunk=False
    )
    spans: list[list[int]] = []  # [old_start, old_end, new_start, new_end]
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
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
    matcher = SequenceMatcher(None, old_paragraphs, new_paragraphs, autojunk=False)
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
            match = next(
                (
                    i
                    for i in olds
                    if i > last_old
                    and SequenceMatcher(
                        None, old_paragraphs[i], new_paragraphs[j], autojunk=False
                    ).ratio()
                    >= _SAME_PARAGRAPH_RATIO
                ),
                None,
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
