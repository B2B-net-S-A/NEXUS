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

Czasy: każda ścieżka biegnie dwa razy, na przemian (stara, nowa, nowa,
stara). Kolumny „ms” to druga, ciepła runda; „zimna” to pierwsza. Pierwszy
pomiar 06.10.2026 mierzył każdą ścieżkę raz, stara szła pierwsza — fraza
„ci/cd” wyszła 1 047 → 7 811 ms, bo nowa ścieżka jako jedyna czytała z dysku
swój tsvector (EXPLAIN: ``read=`` w buforach). Na ciepłym cache: 1 097 → 379 ms.
„niestabilne” = zbiór osób różnił się między rundami (np. zapis w trakcie).
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from typing import Awaitable, Callable

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

Runner = Callable[[], Awaitable[tuple[set[int], float]]]


@dataclass(frozen=True)
class Measurement:
    old_ids: set[int]
    new_ids: set[int]
    old_cold_ms: float
    new_cold_ms: float
    old_ms: float
    new_ms: float
    stable: bool


async def measure_alternating(
    run_old: Runner, run_new: Runner, *, rounds: int = 2
) -> Measurement:
    """Obie ścieżki na przemian; czasy porównania z ostatniej (ciepłej) rundy.

    Kolejność odwraca się co rundę, więc żadna ścieżka nie korzysta stale
    z bloków rozgrzanych przez drugą.
    """
    old_runs: list[tuple[set[int], float]] = []
    new_runs: list[tuple[set[int], float]] = []
    for round_no in range(rounds):
        order = [(run_old, old_runs), (run_new, new_runs)]
        if round_no % 2:
            order.reverse()
        for runner, sink in order:
            sink.append(await runner())
    stable = all(ids == old_runs[0][0] for ids, _ in old_runs) and all(
        ids == new_runs[0][0] for ids, _ in new_runs
    )
    return Measurement(
        old_ids=old_runs[-1][0],
        new_ids=new_runs[-1][0],
        old_cold_ms=old_runs[0][1],
        new_cold_ms=new_runs[0][1],
        old_ms=old_runs[-1][1],
        new_ms=new_runs[-1][1],
        stable=stable,
    )


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
        "| słowo | stara | nowa | ubywa | przybywa | stara ms | nowa ms "
        "| zimna stara | zimna nowa | przykłady ubywa | przykłady przybywa |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|")
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

            async def run_old(term=term):
                with keyword_corpus.force_folded_search(False):
                    return await _ids(db, _whole_word_match(term, "all"))

            async def run_new(term=term):
                with keyword_corpus.force_folded_search(True):
                    return await _ids(db, _whole_word_match(term, "all"))

            m = await measure_alternating(run_old, run_new)
            old, new = m.old_ids, m.new_ids
            lost = sorted(old - new)
            gained = sorted(new - old)
            totals["lost"] += len(lost)
            totals["gained"] += len(gained)
            label = word if m.stable else f"{word} (niestabilne)"
            print(
                f"| {label} | {len(old)} | {len(new)} | {len(lost)} | {len(gained)} "
                f"| {m.old_ms:.0f} | {m.new_ms:.0f} | {m.old_cold_ms:.0f} "
                f"| {m.new_cold_ms:.0f} | {lost[:SAMPLE]} | {gained[:SAMPLE]} |"
            )
    print(f"\nRazem ubywa: {totals['lost']}, przybywa: {totals['gained']}.")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or list(DEFAULT_WORDS)))
