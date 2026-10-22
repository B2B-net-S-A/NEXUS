"""Podział testów na shardy CI: zupełny, rozłączny, wyważony, deterministyczny.

Każdy shard liczy przypisanie SAM, bez koordynacji z pozostałymi. Jeśli dwa
shardy policzyłyby różne partycje, część plików nie poszłaby nigdzie — zielone
CI przy teście, który nie istnieje. Stąd testy własności, nie przykładów.
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import yaml

from tests.conftest import _CI_DURATIONS_FILE, ci_shard_assignment

_BACKEND = Path(__file__).resolve().parents[1]


def _files(n: int) -> list[str]:
    return [f"tests/test_{i:04d}.py" for i in range(n)]


def test_every_file_lands_in_exactly_one_shard() -> None:
    files = _files(97)
    durations = {f: float(i % 13) for i, f in enumerate(files)}
    assignment = ci_shard_assignment(files, 8, durations)
    assert set(assignment) == set(files)
    assert set(assignment.values()) == set(range(8))


def test_assignment_does_not_depend_on_input_order() -> None:
    files = _files(200)
    rng = random.Random(7)
    durations = {f: rng.uniform(0, 60) for f in files}
    shuffled = files[:]
    rng.shuffle(shuffled)
    assert ci_shard_assignment(files, 8, durations) == ci_shard_assignment(
        shuffled, 8, durations
    )


def test_shards_are_balanced_by_measured_time() -> None:
    """Round-robin dawał rozrzut 5,6–9,8 min; LPT ma trzymać się w kilku %."""
    files = _files(400)
    rng = random.Random(3)
    durations = {f: rng.expovariate(1 / 4) for f in files}
    assignment = ci_shard_assignment(files, 8, durations)
    loads = [0.0] * 8
    for name, shard in assignment.items():
        loads[shard] += durations[name]
    assert max(loads) - min(loads) <= max(durations.values())


def test_unmeasured_files_still_get_a_shard() -> None:
    files = _files(30)
    assignment = ci_shard_assignment(files, 4, {})
    assert set(assignment) == set(files)
    assert sorted(list(assignment.values()).count(i) for i in range(4)) == [7, 7, 8, 8]


def test_committed_durations_file_is_valid() -> None:
    data = json.loads(_CI_DURATIONS_FILE.read_text(encoding="utf-8"))
    assert data, "Pusta mapa czasów = shardy znów dzielone na ślepo."
    assert all(name.startswith("tests/") and name.endswith(".py") for name in data), (
        "Klucze to ścieżki od katalogu backend/, np. tests/test_x.py."
    )
    assert all(isinstance(v, (int, float)) and v >= 0 for v in data.values())


def test_ci_matrix_and_combine_agree_on_shard_count() -> None:
    ci = yaml.safe_load(
        (_BACKEND.parent / ".github" / "workflows" / "ci.yml").read_text("utf-8")
    )
    shards = ci["jobs"]["backend-lint-test"]["strategy"]["matrix"]["shard"]
    assert shards == list(range(len(shards)))
    expected = int(ci["jobs"]["backend-coverage-combine"]["env"]["EXPECTED_SHARDS"])
    assert expected == len(shards)


def test_shard_skips_collecting_other_shards_files(monkeypatch) -> None:
    """22.10.2026: shard kolekcjonował wszystkie ~29,9 tys. testów pod tracerem
    pokrycia (1:52–3:00 min) i odrzucał 93%. Teraz cudze pliki odpadają przed
    importem — ale każdy plik musi zostać w dokładnie jednym shardzie."""
    from tests import conftest

    files = sorted(
        path
        for pattern in ("test_*.py", "*_test.py")
        for path in (_BACKEND / "tests").rglob(pattern)
        if "__pycache__" not in path.parts
    )
    owners: dict[Path, list[int]] = {path: [] for path in files}
    try:
        for index in range(3):
            monkeypatch.setenv("CI_SHARD_COUNT", "3")
            monkeypatch.setenv("CI_SHARD_INDEX", str(index))
            conftest._ci_shard_plan.cache_clear()
            for path in files:
                if not conftest.pytest_ignore_collect(path, None):
                    owners[path].append(index)
        helper = _BACKEND / "tests" / "_authz_matrix.py"
        assert conftest.pytest_ignore_collect(helper, None) is None
        assert conftest.pytest_ignore_collect(_BACKEND / "tests", None) is None
        monkeypatch.delenv("CI_SHARD_COUNT")
        conftest._ci_shard_plan.cache_clear()
        assert conftest.pytest_ignore_collect(files[0], None) is None, "Lokalnie no-op."
    finally:
        # Plan liczy się raz na proces — po teście ma odpowiadać prawdziwemu env.
        monkeypatch.undo()
        conftest._ci_shard_plan.cache_clear()
    assert {path: len(shards) for path, shards in owners.items()} == {
        path: 1 for path in files
    }
