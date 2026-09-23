"""0351 (audyt 22.09, druga runda): schemat ma lustro w entrypoincie.

Prod alembic bywa osierocony — `entrypoint.sh` JEST wdrożeniem. Kolumna
w modelu bez lustra = 500 na prodzie przy zielonym CI.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = re.sub(r"\s+", " ", (BACKEND / "entrypoint.sh").read_text())
MIGRATION = (BACKEND / "alembic" / "versions" / "0351_audit_round2.py").read_text()


def test_columns_are_mirrored():
    for needle in (
        '"ALTER TABLE candidate_stage_cvs ADD COLUMN IF NOT EXISTS " '
        '"original_cv_storage_key VARCHAR(512) NULL"',
        '"ALTER TABLE candidate_stage_cvs ADD COLUMN IF NOT EXISTS " '
        '"original_cv_sha256 VARCHAR(64) NULL"',
        '"ALTER TABLE my_people_overrides ADD COLUMN IF NOT EXISTS " '
        '"restore_kind VARCHAR(16) NULL"',
    ):
        assert needle in ENTRYPOINT, needle


def test_checks_are_mirrored_with_the_new_values():
    assert "'non_positive_amount'" in ENTRYPOINT
    assert "'applied', 'needs_assignment', 'unmatched', 'cost_only'" in ENTRYPOINT
    assert "CHECK (restore_kind IS NULL OR restore_kind IN ('pinned'))" in ENTRYPOINT
    for name in re.findall(r"(ck_[a-z_]+)", MIGRATION):
        assert name in ENTRYPOINT, name


def test_migration_chains_after_0350():
    assert 'revision = "0351_audit_round2"' in MIGRATION
    assert 'down_revision = "0350_candidate_keyword_corpus"' in MIGRATION
