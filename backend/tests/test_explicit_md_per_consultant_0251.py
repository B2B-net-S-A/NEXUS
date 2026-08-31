"""Static safety contract for the schema-only MD constraint migration."""

from __future__ import annotations

from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic/versions/0251_explicit_md_per_consultant.py"


def _source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_0251_chains_after_targeted_contract_repair():
    source = _source()
    assert 'revision = "0251_explicit_md_per_consultant"' in source
    assert 'down_revision = "0250_live_order_contract_repair"' in source


def test_explicit_md_uses_the_client_scoped_pool_shape():
    source = _source()
    scoped = source.split("_CLIENT_SCOPED_CHECK =", 1)[1].split("_ROLLBACK_CHECK =", 1)[
        0
    ]
    assert "order_type = 'md' AND is_cost_based = FALSE" in scoped
    assert "client_id IN (155, 38339) AND is_md_budget_based = TRUE" in scoped
    assert "client_id NOT IN (155, 38339) AND is_md_budget_based = FALSE" in scoped


def test_explicit_shared_md_is_limited_to_the_two_established_clients():
    source = _source()
    scoped = source.split("_CLIENT_SCOPED_CHECK =", 1)[1].split("_ROLLBACK_CHECK =", 1)[
        0
    ]
    assert "client_id IN (155, 38339) AND is_md_budget_based = TRUE" in scoped
    assert "client_id NOT IN (155, 38339) AND is_md_budget_based = FALSE" in scoped


def test_upgrade_enforces_new_writes_without_blocking_on_historical_rows():
    upgrade = _source().split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert "_CLIENT_SCOPED_CHECK" in upgrade
    assert "_ROLLBACK_CHECK" not in upgrade
    assert "postgresql_not_valid=True" in upgrade


def test_migration_does_not_rewrite_historical_md_data():
    upgrade = _source().split("def upgrade()", 1)[1].split("def downgrade()", 1)[0]
    assert "UPDATE " not in upgrade.upper()
    assert "drop_constraint" in upgrade
    assert "create_check_constraint" in upgrade


def test_downgrade_keeps_existing_per_line_md_rows_writable():
    source = _source()
    downgrade = source.split("def downgrade()", 1)[1]
    assert "_ROLLBACK_CHECK" in downgrade
    assert "create_check_constraint" in downgrade
    assert "postgresql_not_valid=True" in downgrade
    rollback = source.split("_ROLLBACK_CHECK =", 1)[1].split("def upgrade", 1)[0]
    assert "(order_type = 'md' AND is_cost_based = FALSE)" in rollback
    assert "client_id IN" not in rollback
    assert ") NOT VALID" not in downgrade
    assert "op.execute" not in downgrade
    assert "_PREVIOUS_CHECK" not in source
