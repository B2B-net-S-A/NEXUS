"""Porównanie starej i nowej ścieżki słów kluczowych (korpus złożony, 0385).

Punkt kontrolny przed włączeniem ``KEYWORD_SEARCH_FOLDED_FTS``: dla każdego
słowa liczy zbiór osób starą ścieżką (regexy po ``keyword_doc``/CV/notatkach)
i nową (indeks ``keyword_fold_fts`` + ``content_fold_fts``), pokazuje, ile
osób ubywa i przybywa (z przykładowymi id) oraz czasy. Tylko odczyt
(``SET TRANSACTION READ ONLY``). Uruchamiać PO uzupełnieniu obu kolumn przez
pętlę ``keyword_corpus_backfill`` — inaczej nowa ścieżka nie widzi części
wierszy::

    cd /app && python -m scripts.compare_keyword_fold_fts            # domyślna lista
    cd /app && python -m scripts.compare_keyword_fold_fts java c# scrum

Wyjście: tabela Markdown do akceptacji przez właściciela.
"""

from __future__ import annotations

import asyncio
import sys
import time

from sqlalchemy import select, text

DEFAULT_WORDS: tuple[str, ...] = (
    "java",
    "java*",
    "python",
    "sql",
    "react",
    "angular",
    "vue",
    "node.js",
    "typescript",
    "javascript",
    "*script",
    "c#",
    "c++",
    ".net",
    "asp.net",
    "f#",
    "golang",
    "kotlin",
    "scala",
    "php",
    "devops",
    "docker",
    "kubernetes",
    "terraform",
    "aws",
    "azure",
    "gcp",
    "kafka",
    "spark",
    "selenium",
    "tester",
    "ci/cd",
    "spring boot",
    "scrum",
    "agile",
    "jira",
    "sap",
    "sap abap",
    "power bi",
    "analityk",
    "analityk biznesowy",
    "bankowość",
    "bankow*",
    "ubezpieczenia",
    "łódź",
    "lodz",
    "kraków",
    "krakow",
    "wrocław",
    "gdańsk",
)
SAMPLE = 5


async def _ids(db, clause) -> tuple[set[int], float]:
    from app.models.candidate import Candidate

    started = time.perf_counter()
    rows = (await db.execute(select(Candidate.id).where(clause))).scalars().all()
    return set(rows), (time.perf_counter() - started) * 1000


async def main(words: list[str]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.services import keyword_corpus
    from app.services.advanced_candidate_search import _whole_word_match
    from app.services.keyword_terms import parse_keyword

    keyword_corpus.mark_ready(True)
    print(
        "| słowo | stara | nowa | ubywa | przybywa | stara ms | nowa ms | przykłady ubywa | przykłady przybywa |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---|---|")
    totals = {"lost": 0, "gained": 0}
    async with AsyncSessionLocal() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        await db.execute(text("SET LOCAL statement_timeout = '120s'"))
        pending = (
            await db.execute(text(keyword_corpus.FOLD_PENDING_EXISTS_SQL))
        ).scalar()
        notes_pending = (
            await db.execute(text(keyword_corpus.NOTES_PENDING_EXISTS_SQL))
        ).scalar()
        if pending or notes_pending:
            print(
                f"\nUWAGA: uzupełnianie niezakończone (kandydaci: {bool(pending)}, "
                f"notatki: {bool(notes_pending)}) — nowa ścieżka nie widzi części wierszy.\n"
            )
        for word in words:
            term = parse_keyword(word)
            if term is None:
                continue
            with keyword_corpus.force_folded_search(False):
                old, old_ms = await _ids(db, _whole_word_match(term, "all"))
            with keyword_corpus.force_folded_search(True):
                new, new_ms = await _ids(db, _whole_word_match(term, "all"))
            lost = sorted(old - new)
            gained = sorted(new - old)
            totals["lost"] += len(lost)
            totals["gained"] += len(gained)
            print(
                f"| {word} | {len(old)} | {len(new)} | {len(lost)} | {len(gained)} "
                f"| {old_ms:.0f} | {new_ms:.0f} | {lost[:SAMPLE]} | {gained[:SAMPLE]} |"
            )
    print(f"\nRazem ubywa: {totals['lost']}, przybywa: {totals['gained']}.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or list(DEFAULT_WORDS)))
