"""Runda 6 audytu (RODO) — reguły bez bazy: nagrobek, wzorce linków, CV odpięte.

Testy z bazą (DELETE przez API, import Traffita, scalanie) są w
``test_candidate_erasure_leftovers.py``.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND = Path(__file__).resolve().parents[1]


def test_tombstone_is_keyed_hmac_without_the_raw_id(monkeypatch):
    from app.services import candidate_audit

    monkeypatch.setattr(
        candidate_audit.settings,
        "CANDIDATE_IDENTITY_FINGERPRINT_KEY",
        "k" * 40,
    )
    first = candidate_audit.candidate_source_tombstone("traffit", "48895")
    assert first == candidate_audit.candidate_source_tombstone("traffit", 48895)
    assert len(first) == 64 and "48895" not in first
    # Inne źródło, inny identyfikator — inny nagrobek.
    assert first != candidate_audit.candidate_source_tombstone("jjit", "48895")
    assert first != candidate_audit.candidate_source_tombstone("traffit", "48896")
    monkeypatch.setattr(
        candidate_audit.settings, "CANDIDATE_IDENTITY_FINGERPRINT_KEY", "q" * 40
    )
    assert first != candidate_audit.candidate_source_tombstone("traffit", "48895")


def test_tombstone_fails_closed_without_key(monkeypatch):
    from app.services import candidate_audit

    monkeypatch.setattr(
        candidate_audit.settings, "CANDIDATE_IDENTITY_FINGERPRINT_KEY", "  "
    )
    with pytest.raises(RuntimeError):
        candidate_audit.candidate_source_tombstone("traffit", "1")


@pytest.mark.parametrize(
    "link, hit",
    [
        ("/candidates/57", True),
        ("/candidates/57?tab=recruitments", True),
        ("/jobs/9?candidate=57", True),
        ("/jobs/9?tab=board&candidate=57&panel=cv", True),
        ("/calendar?cycle=57-9", True),
        ("/candidates/570", False),
        ("/candidates/5", False),
        ("/jobs/9?candidate=570", False),
        ("/calendar?cycle=570-9", False),
        ("/jobs/57", False),
        (None, False),
    ],
)
def test_link_patterns_match_only_this_person(link, hit):
    # Składnia wzorców jest wspólna dla ARE Postgresa i `re` Pythona
    # (lookahead, klasa znaków, grupa).
    from app.services.candidate_erasure_leftovers import candidate_link_patterns

    patterns = candidate_link_patterns(57)
    assert any(link and re.search(p, link) for p in patterns) is hit


def test_merge_rewrites_keep_the_rest_of_the_link():
    from app.services.candidate_erasure_leftovers import candidate_link_rewrites

    def rewrite(link: str) -> str:
        for pattern, replacement in candidate_link_rewrites(57, 3):
            # `\1` Postgresa = `\g<1>` Pythona.
            link = re.sub(pattern, replacement.replace("\\1", "\\g<1>"), link)
        return link

    assert rewrite("/candidates/57?tab=x") == "/candidates/3?tab=x"
    assert rewrite("/jobs/9?candidate=57&panel=cv") == "/jobs/9?candidate=3&panel=cv"
    assert rewrite("/calendar?cycle=57-9") == "/calendar?cycle=3-9"
    assert rewrite("/candidates/570") == "/candidates/570"


@pytest.mark.parametrize(
    "candidate_id, mode, stage_id, detached",
    [
        (None, "new", None, True),
        (None, "upload", 12, True),
        # „Generuj bez dodawania” — legalny dokument bez kandydata.
        (None, "upload", None, False),
        (5, "new", 12, False),
        (5, "upload", None, False),
    ],
)
def test_detached_generated_document_rule(candidate_id, mode, stage_id, detached):
    from app.services.candidate_erasure_leftovers import (
        is_detached_generated_document,
    )

    row = SimpleNamespace(candidate_id=candidate_id, mode=mode, stage_id=stage_id)
    assert is_detached_generated_document(row) is detached


def test_merge_does_not_tombstone_the_source_record():
    # Ocalały przejmuje `external_id` duplikatu — nagrobek by go odciął.
    source = (BACKEND / "app" / "services" / "candidate_merge.py").read_text()
    assert "purged_candidates" not in source
    assert "PurgedCandidate" not in source
    assert "candidate_source_tombstone" not in source


def test_importer_checks_tombstones_before_the_adopt_path():
    source = (BACKEND / "app" / "services" / "traffit" / "importer.py").read_text()
    body = source[source.index("async def import_candidates(") :]
    body = body[: body.index("\n    async def ", 10)]
    tomb = body.index("candidate_source_tombstone(")
    assert tomb < body.index("email_to_id.get(email_lc)")
    assert tomb < body.index("_UPSERT_CANDIDATE, params")


def test_migration_is_mirrored_in_entrypoint_and_probed():
    import importlib.util

    path = BACKEND / "alembic" / "versions" / "0388_purged_candidates.py"
    spec = importlib.util.spec_from_file_location("m0388", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.down_revision == "0387_keyword_fold_combining"

    def collapse(sql: str) -> str:
        return re.sub(r"\s+", " ", sql).strip()

    entrypoint = collapse((BACKEND / "entrypoint.sh").read_text())
    for statement in module.DDL_STATEMENTS:
        assert "IF NOT EXISTS" in statement
        assert collapse(statement) in entrypoint
    main = (BACKEND / "app" / "main.py").read_text()
    assert '("purged_candidates", PurgedCandidate)' in main
    models = (BACKEND / "app" / "models" / "__init__.py").read_text()
    assert "from app.models.purged_candidate import PurgedCandidate" in models
