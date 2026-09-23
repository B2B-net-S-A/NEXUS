"""0355: kolumny i CHECK-i zakończenia współpracy mają lustro w entrypoincie.

Prod alembic bywa osierocony — `entrypoint.sh` JEST wdrożeniem. Model czyta
nowe kolumny przy KAŻDYM odczycie kontraktu, więc brak lustra = 500 na całym
module Kontrakty przy zielonym CI (gdzie działa migracja).
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ENTRYPOINT = (BACKEND / "entrypoint.sh").read_text()
MIGRATION = (
    BACKEND / "alembic" / "versions" / "0355_contract_agreement_termination.py"
).read_text()


def _collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_columns_are_mirrored():
    flat = _collapse(ENTRYPOINT)
    for table, column in (
        ("contracts", "agreement_termination_mode"),
        ("contracts", "agreement_termination_party"),
        ("contracts", "agreement_termination_signed_on"),
        ("contracts", "agreement_last_day"),
        ("contracts", "notice_period_months"),
        ("b2b_generated_contracts", "termination_mode"),
        ("b2b_generated_contracts", "termination_party"),
        ("b2b_generated_contracts", "termination_signed_on"),
        ("b2b_generated_contracts", "project_end_date"),
        ("b2b_generated_contracts", "termination_restore"),
        ("b2b_generated_contracts", "previous_generated_contract_id"),
        ("b2b_generated_contract_status_events", "details"),
    ):
        assert f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column}" in flat, (
            table,
            column,
        )
        assert column in MIGRATION, column


def test_enum_values_and_constraints_are_mirrored():
    flat = _collapse(ENTRYPOINT)
    migration = _collapse(MIGRATION)
    for value in ("termination_notice", "termination_agreement"):
        needle = f"ALTER TYPE contractdocumenttype ADD VALUE IF NOT EXISTS '{value}'"
        assert needle in flat, needle
    names = set(re.findall(r"\b((?:ck|ix)_[a-z0-9_]+)", MIGRATION))
    assert names
    for name in names:
        assert name in ENTRYPOINT, name
    for needle in (
        "agreement_termination_mode IN ('notice', 'mutual_agreement')",
        "agreement_termination_party IN ('consultant', 'company')",
        "notice_period_months BETWEEN 1 AND 24",
    ):
        assert needle in flat, needle
        assert needle in migration, needle


def test_migration_chains_after_0354():
    assert 'revision = "0355_contract_agreement_termination"' in MIGRATION
    assert 'down_revision = "0354_order_change_checks"' in MIGRATION


def test_model_enum_matches_migration():
    from app.models.contract_document import ContractDocumentType

    assert ContractDocumentType.termination_notice.value == "termination_notice"
    assert ContractDocumentType.termination_agreement.value == "termination_agreement"
