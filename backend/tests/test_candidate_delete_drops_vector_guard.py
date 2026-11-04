"""Każde miejsce, które kasuje wiersz `candidates`, kasuje też jego wektor.

Qdrant nie ma kluczy obcych, więc punkt osoby usuniętej z bazy zostaje w
indeksie, dopóki ktoś go jawnie nie skasuje. Hurtowe scalenie duplikatów
z 07.08.2026 (`scripts/merge_duplicate_candidates.py`, zanim dostało
kasowanie wektorów w #1088) zostawiło tak 1 932 punkty: zajmowały miejsca
w puli 200 najbliższych zakładki „Podobni” i w top-K wyszukiwania
semantycznego, a każdy niósł tekst CV osoby, której już nie ma. Wisiały do
23.10.2026, bo nic nie mówiło, że przybyły.

Strażnik nie sprawdza, czy kasowanie wektora jest poprawne (to robią testy
ścieżek), tylko że nowa ścieżka kasowania kandydatów w ogóle o nim pamięta.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOTS = ("app", "scripts", "alembic")

CANDIDATE_ROW_DELETE = re.compile(
    r"DELETE\s+FROM\s+candidates\b"
    r"|\bdelete\(\s*Candidate\s*\)"
    r"|\.delete\(\s*candidate\s*\)",
    re.IGNORECASE,
)
# Natychmiastowe kasowanie punktu albo trwały retry w outboxie indeksu.
VECTOR_DELETE = re.compile(
    r"delete_candidate_embedding|_delete_qdrant_points"
    r"|IndexOutboxEvent\((?:(?!\)\s*\)).)*operation=\"delete\"",
    re.DOTALL,
)


def _sources() -> list[Path]:
    files = [BACKEND / "entrypoint.sh"]
    for root in ROOTS:
        files.extend(sorted((BACKEND / root).rglob("*.py")))
    return files


def _deleting_files() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        if CANDIDATE_ROW_DELETE.search(text):
            found[str(path.relative_to(BACKEND))] = text
    return found


def test_every_candidate_row_delete_also_drops_the_vector():
    missing = sorted(
        name
        for name, text in _deleting_files().items()
        if not VECTOR_DELETE.search(text)
    )
    assert not missing, (
        "Te pliki kasują wiersze `candidates`, ale nie kasują punktu w Qdrancie "
        "(`delete_candidate_embedding` po commicie i `IndexOutboxEvent(..., "
        'operation="delete")` w tej samej transakcji, jak '
        "`app/services/candidate_hard_delete.py`): " + ", ".join(missing)
    )


def test_guard_sees_the_known_delete_paths():
    # Gdyby wzorzec przestał cokolwiek łapać, strażnik wyżej przechodziłby
    # zawsze — te trzy ścieżki muszą być widoczne.
    names = set(_deleting_files())
    assert {
        "app/services/candidate_hard_delete.py",
        "app/services/candidate_merge.py",
        "scripts/merge_duplicate_candidates.py",
    } <= names


def test_outbox_marker_needs_a_delete_operation():
    upsert_only = 'IndexOutboxEvent(entity_type="candidate", operation="upsert")'
    staged = 'IndexOutboxEvent(\n    entity_id=cid,\n    operation="delete",\n)'
    assert not VECTOR_DELETE.search(upsert_only)
    assert VECTOR_DELETE.search(staged)
