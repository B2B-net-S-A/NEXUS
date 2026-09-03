"""Schema/bootstrap contract for configurable privileged-action access."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

from app.models.user import UserRole
from app.services.action_permissions import (
    DEFAULT_ROLE_ACTION_ACCESS,
    ProductAction,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_ROOT / "alembic/versions/0273_action_permissions.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("action_rbac_0273", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_seed_exactly_matches_bootstrap_matrix() -> None:
    migration = _migration_module()
    action = ProductAction.b2b_contract_generator
    expected = {
        role.value: DEFAULT_ROLE_ACTION_ACCESS[role][action].name for role in UserRole
    }
    assert migration.ACTION == action.value
    assert migration.ROLE_DEFAULTS == expected
    upgrade_source = inspect.getsource(migration.upgrade)
    assert "SELECT 1 FROM rbac_role_action_permissions" in upgrade_source
    assert "if matrix_empty:" in upgrade_source


def test_entrypoint_recovery_seed_is_complete_and_fail_closed() -> None:
    entrypoint = (BACKEND_ROOT / "entrypoint.sh").read_text()
    assert "CREATE TABLE IF NOT EXISTS rbac_role_action_permissions" in entrypoint
    assert "CREATE TABLE IF NOT EXISTS rbac_user_action_overrides" in entrypoint

    seed_start = entrypoint.index(
        "INSERT INTO rbac_role_action_permissions (role, action, access)"
    )
    seed_end = entrypoint.index("# 0256: seed domyślnej punktacji Insights", seed_start)
    seed = entrypoint[seed_start:seed_end]
    assert "ON CONFLICT (role, action) DO NOTHING" in seed
    assert "DO UPDATE" not in seed
    assert "SELECT 1 FROM rbac_role_action_permissions" in seed
    for role in UserRole:
        access = DEFAULT_ROLE_ACTION_ACCESS[role][
            ProductAction.b2b_contract_generator
        ].name
        assert f"('{role.value}', 'b2b_contract_generator', '{access}')" in seed
