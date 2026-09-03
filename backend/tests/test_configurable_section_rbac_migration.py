"""Schema/bootstrap contract for configurable product-section access."""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

from app.models.user import UserRole
from app.services.section_permissions import (
    DEFAULT_ROLE_SECTION_ACCESS,
    ProductSection,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = BACKEND_ROOT / "alembic/versions/0269_configurable_section_rbac.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("section_rbac_0269", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_seed_exactly_matches_bootstrap_matrix() -> None:
    migration = _migration_module()
    expected = {
        role.value: {
            section.value: DEFAULT_ROLE_SECTION_ACCESS[role][section].name
            for section in ProductSection
        }
        for role in UserRole
    }
    assert migration.ROLE_DEFAULTS == expected
    assert tuple(migration.SECTIONS) == tuple(
        section.value for section in ProductSection
    )
    upgrade_source = inspect.getsource(migration.upgrade)
    assert "SELECT NOT EXISTS (" in upgrade_source
    assert "SELECT 1 FROM rbac_role_section_permissions" in upgrade_source
    assert "if matrix_empty:" in upgrade_source


def test_entrypoint_recovery_seed_is_complete_and_never_overwrites_admin_edits() -> (
    None
):
    entrypoint = (BACKEND_ROOT / "entrypoint.sh").read_text()
    assert "CREATE TABLE IF NOT EXISTS rbac_policy_state" in entrypoint
    assert "CREATE TABLE IF NOT EXISTS rbac_role_section_permissions" in entrypoint
    assert "CREATE TABLE IF NOT EXISTS rbac_user_section_overrides" in entrypoint
    assert "CREATE TABLE IF NOT EXISTS rbac_permission_audit" in entrypoint

    seed_start = entrypoint.index(
        "INSERT INTO rbac_role_section_permissions (role, section, access)"
    )
    seed_end = entrypoint.index("# 0256: seed domyślnej punktacji Insights", seed_start)
    seed = entrypoint[seed_start:seed_end]
    assert "ON CONFLICT (role, section) DO NOTHING" in seed
    assert "DO UPDATE" not in seed
    assert "WHERE NOT EXISTS (" in seed
    assert "SELECT 1 FROM rbac_role_section_permissions" in seed
    for role in UserRole:
        for section in ProductSection:
            access = DEFAULT_ROLE_SECTION_ACCESS[role][section].name
            assert f"('{role.value}', '{section.value}', '{access}')" in seed
