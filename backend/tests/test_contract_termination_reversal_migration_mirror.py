"""0357: migawka zakończenia i powrót po przerwie mają lustro w entrypoincie.

Prod alembic bywa osierocony — `entrypoint.sh` JEST wdrożeniem. Bez lustra
zakończenie kontraktu (zapis migawki) padałoby na UndefinedTable przy zielonym
CI, gdzie działa migracja.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = (BACKEND / "entrypoint.sh").read_text()
MIGRATION = (
    BACKEND / "alembic" / "versions" / "0357_contract_termination_reversal.py"
).read_text()


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_table_column_and_constraints_are_mirrored():
    flat = _collapse(ENTRYPOINT)
    migration = _collapse(MIGRATION)
    for needle in (
        "CREATE TABLE IF NOT EXISTS contract_termination_snapshots",
        "CHECK (status IN ('open', 'reversed', 'superseded'))",
        "CHECK (source IN ('termination', 'history'))",
        "CHECK (status <> 'reversed' OR reversed_at IS NOT NULL)",
        "ON contract_termination_snapshots (contract_id) WHERE status = 'open'",
        "ADD COLUMN IF NOT EXISTS returned_from_contract_id",
    ):
        assert needle in flat, needle
        assert needle in migration, needle


def test_every_named_object_in_the_migration_exists_in_the_entrypoint():
    names = set(re.findall(r"\b((?:ck|ix|ux)_contract[a-z_]+)", MIGRATION))
    assert names
    for name in names:
        assert name in ENTRYPOINT, name


def test_migration_chains_after_0356():
    assert 'revision = "0357_contract_termination_reversal"' in MIGRATION
    assert 'down_revision = "0356_kpi_targets_editor_reports"' in MIGRATION


def test_one_shot_repair_runs_at_startup_without_names_in_the_log():
    assert 'startup_phase "repair-termination-reversal"' in ENTRYPOINT
    assert "run_termination_reversal_repair" in ENTRYPOINT
