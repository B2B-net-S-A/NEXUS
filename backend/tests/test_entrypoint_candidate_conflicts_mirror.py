"""Migracja 0321 (rejestr konfliktów) i jej lustro w ``entrypoint.sh``.

Prod alembic bywa osierocony — safety-net JEST wdrożeniem. Bez kolumn
``deactivated_*`` dezaktywacja konfliktu wywala się na produkcji (500), a bez
DROP starego indeksu (kandydat, klient) drugi TYP konfliktu u tego samego
klienta dostaje 409, choć model i migracja już na to pozwalają.

Źródło czytane jako tekst, bez wykonania heredocu (import podmienia
``sys.modules["asyncpg"]`` atrapą i zatruwa testy z bazą w tej samej sesji).
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.candidate_conflict import CandidateConflict

_BACKEND = Path(__file__).resolve().parents[1]
_ENTRYPOINT = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
_MIGRATION = (
    _BACKEND / "alembic" / "versions" / "0321_conflict_audit_type_unique.py"
).read_text(encoding="utf-8")


def _section(name: str) -> str:
    start = _ENTRYPOINT.index(f"\n{name} = [")
    end = _ENTRYPOINT.index("\n]\n", start)
    return _ENTRYPOINT[start:end]


def _shape(text: str) -> str:
    # Sklejenie literałów Pythona ("a " "b") i znormalizowanie białych znaków.
    return " ".join(re.sub(r'"\s*\n\s*"', "", text).split()).lower()


def test_audit_columns_have_a_mirror_in_the_column_phase():
    columns = _shape(_section("_COLUMN_STATEMENTS"))
    for column in ("deactivated_at", "deactivated_by", "deactivation_reason"):
        assert column in CandidateConflict.__table__.columns
        assert column in _MIGRATION
        assert (
            f"alter table candidate_conflicts add column if not exists {column}"
            in columns
        ), f"brak lustra kolumny {column} w _COLUMN_STATEMENTS"
    assert "references users(id) on delete set null" in columns


def test_old_pair_index_is_dropped_in_the_column_phase_not_the_index_phase():
    assert "drop index if exists uq_candidate_conflict_active" in _shape(
        _section("_COLUMN_STATEMENTS")
    )
    assert 'uq_candidate_conflict_active"' not in _section("_INDEX_STATEMENTS")
    assert "drop index" not in _shape(_section("_INDEX_STATEMENTS"))


def test_new_indexes_are_built_concurrently_with_the_model_names():
    index_phase = _shape(_section("_INDEX_STATEMENTS"))
    model_indexes = {index.name: index for index in CandidateConflict.__table__.indexes}
    assert "uq_candidate_conflict_active" not in model_indexes

    unique = model_indexes["uq_candidate_conflict_active_type"]
    assert unique.unique
    assert [c.name for c in unique.columns] == ["candidate_id", "client_id", "type"]
    assert (
        "create unique index concurrently if not exists "
        "uq_candidate_conflict_active_type on candidate_conflicts "
        "(candidate_id, client_id, type) where active = true"
    ) in index_phase

    expires = model_indexes["ix_candidate_conflicts_active_expires"]
    assert [c.name for c in expires.columns] == ["expires_at"]
    assert (
        "create index concurrently if not exists "
        "ix_candidate_conflicts_active_expires on candidate_conflicts (expires_at) "
        "where active = true and expires_at is not null"
    ) in index_phase

    for name in (
        "uq_candidate_conflict_active_type",
        "ix_candidate_conflicts_active_expires",
    ):
        assert name in _MIGRATION


def test_old_conflict_zeroed_scores_are_invalidated_once_per_row():
    data = _shape(_section("_DATA_STATEMENTS"))
    assert "update candidate_job_match_scores set stale = true" in data
    assert "where stale = false" in data
    assert "'active_conflict', 'client_excluded'" in data
