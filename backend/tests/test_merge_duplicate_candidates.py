"""Unit tests for duplicate-candidate cleanup.

DB-free: exercises the merge-SQL builder. The actual UPDATE/DELETE SQL is
covered end-to-end by the script's --dry-run against the real DB (see plan
verification §1). The TalentRadar importer and its match-resolution tests were
removed on 25.11.2026 together with the import.
"""

from __future__ import annotations

from scripts.merge_duplicate_candidates import (
    _JSON_COLS,
    _NULLABLE_COLS,
    _TEXT_COLS,
    _build_cv_port_sql,
)


# ── merge-script: CV port SQL builder ────────────────────────────────────────


def test_cv_port_sql_targets_canonical_from_merge_pairs():
    sql = _build_cv_port_sql()
    assert "UPDATE candidates c" in sql
    assert "FROM merge_pairs mp" in sql
    assert "JOIN candidates d ON d.id = mp.dup_id" in sql
    assert "c.id = mp.canonical_id" in sql
    assert "updated_at = NOW()" in sql


def test_cv_port_sql_covers_every_cv_column():
    sql = _build_cv_port_sql()
    for col in (*_TEXT_COLS, *_JSON_COLS, *_NULLABLE_COLS):
        # Each column must appear both in the SET clause and the enrich WHERE.
        assert f"{col} =" in sql, f"{col} missing from SET clause"
        assert f"d.{col}" in sql, f"{col} missing from enrich predicate"


def test_cv_port_sql_only_fills_empty_canonical():
    """Text/JSON columns are guarded so canonical data is never overwritten."""
    sql = _build_cv_port_sql()
    # text columns: CASE WHEN canonical empty THEN dup ELSE keep canonical
    assert "ELSE c.raw_cv_text END" in sql
    # json columns: empty means NULL / '{}' / '[]' / 'null'
    assert "c.cv_extracted_data::text IN ('{}', '[]', 'null')" in sql
    # nullable columns use COALESCE (canonical wins when present)
    assert "cv_storage_key = COALESCE(c.cv_storage_key, d.cv_storage_key)" in sql
