"""Porównanie ścieżek słów kluczowych mierzy obie na ciepłym cache.

Pomiar 06.10.2026 (PR #2056): fraza „ci/cd” wyszła 1 047 → 7 811 ms, ale
EXPLAIN (ANALYZE, BUFFERS) pokazał, że nowa ścieżka czytała z dysku tsvector,
którego stara ścieżka chwilę wcześniej nie dotknęła (``read=`` w buforach),
a stara korzystała z bloków rozgrzanych przez siebie. Na ciepłym cache ta sama
fraza: stara 1 097 ms, nowa 379 ms. Skrypt mierzy więc obie ścieżki na
przemian i porównuje ostatnią rundę, a pierwszą (zimną) pokazuje osobno.
"""

from __future__ import annotations

import asyncio

from scripts.compare_keyword_fold_fts import measure_alternating


def test_measures_both_paths_alternately_and_reports_the_warm_round():
    calls: list[str] = []
    times = {"old": iter([900.0, 300.0]), "new": iter([7800.0, 150.0])}

    async def run(name: str):
        calls.append(name)
        return {1, 2, 3} if name == "old" else {2, 3, 4}, next(times[name])

    result = asyncio.run(
        measure_alternating(lambda: run("old"), lambda: run("new"), rounds=2)
    )

    assert calls == ["old", "new", "new", "old"]
    assert result.old_ids == {1, 2, 3}
    assert result.new_ids == {2, 3, 4}
    assert result.old_cold_ms == 900.0
    assert result.new_cold_ms == 7800.0
    assert result.old_ms == 300.0
    assert result.new_ms == 150.0
    assert result.stable


def test_marks_a_result_that_changed_between_rounds():
    sets = iter([{1}, {1}, {1, 2}, {1}])

    async def run():
        return next(sets), 1.0

    result = asyncio.run(measure_alternating(run, run, rounds=2))

    assert not result.stable
