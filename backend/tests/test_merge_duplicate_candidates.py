"""Unit tests for duplicate-candidate cleanup + TalentRadar cross-source dedup.

DB-free: exercises the merge-SQL builder and the importer's match-resolution
precedence (external_id → email → corroborated dedup), which is where the
correctness risk lives. The actual UPDATE/DELETE SQL is covered end-to-end by
the script's --dry-run against the real DB (see plan verification §1).
"""

from __future__ import annotations

import pytest

from app.services import talent_radar_importer as tri
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


# ── importer: cross-source match resolution ──────────────────────────────────


def _make_importer() -> tri.TalentRadarImporter:
    # target_db is unused on the in-memory map paths; dedup path is monkeypatched.
    return tri.TalentRadarImporter(source_dsn="", target_db=object(), dry_run=True)


@pytest.mark.asyncio
async def test_external_id_match_wins_over_email():
    imp = _make_importer()
    imp._ext_id_to_id = {"123": 10}
    imp._email_to_id = {"jan@x.pl": 20}
    payload = {
        "external_id": "123",
        "email": "jan@x.pl",
        "name": "Jan",
        "lastname": "K",
    }
    assert await imp._find_existing_id(payload) == 10


@pytest.mark.asyncio
async def test_falls_back_to_email_when_external_id_unknown():
    imp = _make_importer()
    imp._ext_id_to_id = {}
    imp._email_to_id = {"jan@x.pl": 20}
    payload = {
        "external_id": "999",
        "email": "JAN@x.pl ",
        "name": "Jan",
        "lastname": "K",
    }
    assert await imp._find_existing_id(payload) == 20


@pytest.mark.asyncio
async def test_namesake_only_dedup_is_rejected(monkeypatch):
    """A bare name match (no hard corroborator) must NOT merge — different
    people share names."""

    async def fake_dupes(*args, **kwargs):
        return [{"candidate_id": 30, "match_reasons": ["name_exact"]}]

    monkeypatch.setattr(tri, "find_candidate_duplicates", fake_dupes)
    imp = _make_importer()
    payload = {
        "external_id": "new-1",
        "email": None,
        "name": "Anna",
        "lastname": "Nowak",
    }
    assert await imp._find_existing_id(payload) is None


@pytest.mark.asyncio
async def test_corroborated_dedup_merges(monkeypatch):
    """Name + a hard corroborator (phone/linkedin/email) is trusted."""

    async def fake_dupes(*args, **kwargs):
        return [{"candidate_id": 30, "match_reasons": ["name_exact", "phone_exact"]}]

    monkeypatch.setattr(tri, "find_candidate_duplicates", fake_dupes)
    imp = _make_importer()
    payload = {
        "external_id": "new-2",
        "email": None,
        "name": "Anna",
        "lastname": "Nowak",
    }
    assert await imp._find_existing_id(payload) == 30


@pytest.mark.asyncio
async def test_no_match_returns_none(monkeypatch):
    async def fake_dupes(*args, **kwargs):
        return []

    monkeypatch.setattr(tri, "find_candidate_duplicates", fake_dupes)
    imp = _make_importer()
    payload = {
        "external_id": "brand-new",
        "email": "fresh@x.pl",
        "name": "Ola",
        "lastname": "Z",
    }
    assert await imp._find_existing_id(payload) is None


@pytest.mark.asyncio
async def test_placeholder_name_skips_dedup_fallback(monkeypatch):
    """A '?' name (source had no name) must not trigger the dedup fallback."""
    called = False

    async def fake_dupes(*args, **kwargs):
        nonlocal called
        called = True
        return [{"candidate_id": 99, "match_reasons": ["name_exact", "phone_exact"]}]

    monkeypatch.setattr(tri, "find_candidate_duplicates", fake_dupes)
    imp = _make_importer()
    payload = {"external_id": "x", "email": None, "name": "?", "lastname": "?"}
    assert await imp._find_existing_id(payload) is None
    assert called is False


# ── importer: merge params ───────────────────────────────────────────────────


def test_merge_params_serializes_json_and_sets_nexus_id():
    payload = {
        "skills": ["python", "go"],
        "languages": ["pl", "en"],
        "cv_extracted_data": {"a": 1},
        "email": "x@y.pl",
        "raw_cv_text": "CV",
    }
    params = tri.TalentRadarImporter._merge_params(payload, nexus_id=42)
    assert params["nexus_id"] == 42
    assert params["skills"] == '["python", "go"]'
    # Languages are persisted only by candidate_language_writer after the
    # candidate id is resolved; the raw SQL candidate merge cannot write them.
    assert "languages" not in params
    assert params["cv_extracted_data"] == '{"a": 1}'
    # absent keys default to safe values (None / empty JSON), never KeyError
    assert params["phone"] is None
    # Location is persisted exclusively by the canonical writer after the
    # candidate id is resolved, never by this raw-SQL parameter set.
    assert "location" not in params
