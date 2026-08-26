"""Kontrakt migracji 0245 i produkcyjnego safety-netu entrypointu."""

from __future__ import annotations

import ast
import re
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0245_cyfrowy_polsat_shared_md_orders.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"
MODEL = BACKEND / "app" / "models" / "client_order_group.py"
MAIN = BACKEND / "app" / "main.py"


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace('"', ""))


def test_shared_md_migration_is_linear_from_0244():
    values: dict[str, object] = {}
    for node in ast.parse(MIGRATION.read_text(encoding="utf-8")).body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                values[target.id] = node.value.value
    assert values["revision"] == "0245_cyfrowy_polsat_shared_md_orders"
    assert values["down_revision"] == "0244_cardif_client_reassignment"


def test_model_migration_and_entrypoint_share_the_complete_contract():
    model = MODEL.read_text(encoding="utf-8")
    migration = _flat(MIGRATION.read_text(encoding="utf-8"))
    entrypoint = _flat(ENTRYPOINT.read_text(encoding="utf-8"))

    for column in (
        "is_md_budget_based",
        "md_budget_total",
        "md_budget_remaining",
        "md_budget_manual_adjustment",
    ):
        assert column in model
        assert f"ADD COLUMN IF NOT EXISTS {column}" in entrypoint
        assert column in migration

    table = "client_order_group_md_consumptions"
    assert table in model
    assert f"CREATE TABLE IF NOT EXISTS {table}" in entrypoint
    assert table in migration

    for constraint in (
        "ck_client_order_groups_settlement_exclusive",
        "ck_client_order_groups_md_budget_coherence",
        "ck_group_md_consumptions_period",
        "ck_group_md_consumptions_source",
        "ck_group_md_consumptions_nonnegative",
    ):
        assert constraint in model
        assert constraint in migration
        assert constraint in entrypoint


def test_group_month_uniqueness_and_deep_health_probe_are_mirrored():
    migration = _flat(MIGRATION.read_text(encoding="utf-8"))
    entrypoint = _flat(ENTRYPOINT.read_text(encoding="utf-8"))
    index = "ux_group_md_consumptions_group_month"
    assert index in migration
    assert f"CREATE UNIQUE INDEX IF NOT EXISTS {index}" in entrypoint
    assert '("client_order_group_md_consumptions"' in MAIN.read_text(encoding="utf-8")
