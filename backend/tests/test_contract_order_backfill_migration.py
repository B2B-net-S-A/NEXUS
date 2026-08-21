"""Kontrakt jednorazowej, precyzyjnej korekty danych po migracji 0238."""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = (
    BACKEND / "alembic" / "versions" / "0239_bik_contract_order_backfill.py"
)
ENTRYPOINT = BACKEND / "entrypoint.sh"


def test_backfill_chains_onto_contract_order_workflows():
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                values[target.id] = node.value.value

    assert values["revision"] == "0239_bik_contract_order_backfill"
    assert values["down_revision"] == "0238_contract_order_workflows"


def test_both_delivery_paths_use_the_same_one_shot_marker_and_exact_targets():
    for source in (MIGRATION, ENTRYPOINT):
        text = source.read_text(encoding="utf-8")
        assert "0239_bik_contract_order_backfill" in text
        assert "contract.id = 571" in text
        assert "contract.client_id = 18" in text
        assert "btrim(candidate.name) = 'Robert'" in text
        assert "btrim(candidate.lastname) LIKE 'Łuszcz%'" in text
        assert "order_group.order_number = '4500030684'" in text
        assert "order_group.start_date = DATE '2026-09-11'" in text
        assert "order_group.predecessor_group_id IS NOT NULL" in text
        assert "order_group.start_date > CURRENT_DATE" in text


def test_backfill_only_reclassifies_expected_current_states():
    for source in (MIGRATION, ENTRYPOINT):
        text = source.read_text(encoding="utf-8")
        assert "contract.status = 'draft'::contractstatus" in text
        assert "order_group.status = 'active'" in text
        assert "SET status = 'scheduled'" in text
        assert "SET status = 'draft'::clientorderstatus" in text
        assert "filled_at = NULL" in text


def test_backfill_is_ambiguous_fail_closed_and_not_automatically_reversed():
    migration = MIGRATION.read_text(encoding="utf-8")
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "IF target_group_count > 1" in migration
    assert "IF target_group_count > 1" in entrypoint
    assert "'rollback', 'manual_only'" in migration
    downgrade = migration.split("def downgrade()", 1)[1]
    assert "UPDATE contracts" not in downgrade
    assert "UPDATE client_order_groups" not in downgrade
