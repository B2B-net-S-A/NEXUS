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

# Seed 0273 (i jego lustro w entrypoint.sh) opisuje macierz z dnia migracji.
# Późniejsze decyzje zmieniają DEFAULT_ROLE_ACTION_ACCESS, a nie historyczny
# seed — każde takie odejście musi być wpisane tutaj jawnie (rola → wartość
# w seedzie, wartość w kodzie). Świeże środowisko dostaje wartość z seedu,
# więc wpis tutaj oznacza też potrzebę migracji danych.
#
# 22.09.2026 (decyzja Artura): TCM ma pełny generator B2B. Produkcja ma
# „manage" od 03–04.09 (panel RBAC); świeża baza z seedu 0273 da „view".
SEED_DIVERGENCE_AFTER_0273: dict[str, tuple[str, str]] = {
    UserRole.talent_community_manager.value: ("view", "manage"),
}


def _seeded_generator_access(role: UserRole) -> str:
    current = DEFAULT_ROLE_ACTION_ACCESS[role][ProductAction.b2b_contract_generator]
    divergence = SEED_DIVERGENCE_AFTER_0273.get(role.value)
    if divergence is None:
        return current.name
    seeded, expected_current = divergence
    assert current.name == expected_current, (
        f"{role.value}: kod ma {current.name}, a rozbieżność z seedem opisuje "
        f"{expected_current} — zaktualizuj SEED_DIVERGENCE_AFTER_0273"
    )
    return seeded


def _migration_module():
    spec = importlib.util.spec_from_file_location("action_rbac_0273", MIGRATION_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_seed_exactly_matches_bootstrap_matrix() -> None:
    migration = _migration_module()
    action = ProductAction.b2b_contract_generator
    expected = {role.value: _seeded_generator_access(role) for role in UserRole}
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
    # Recovery seed odtwarza stan PO 0347 — czyli aktualne domyślne z kodu.
    for role in UserRole:
        access = DEFAULT_ROLE_ACTION_ACCESS[role][
            ProductAction.b2b_contract_generator
        ].name
        assert f"('{role.value}', 'b2b_contract_generator', '{access}')" in seed


def test_0347_closes_the_tcm_seed_divergence_only_for_untouched_rows() -> None:
    path = MIGRATION_PATH.parent / "0347_tcm_b2b_generator_manage.py"
    source = path.read_text()
    assert 'down_revision = "0346_kpi_catalog_unification"' in source
    for role, (seeded, current) in SEED_DIVERGENCE_AFTER_0273.items():
        assert f"role = '{role}'" in source
        assert f"access = '{seeded}'" in source
        assert f"SET access = '{current}'" in source
    # Decyzja administratora z panelu RBAC (updated_by) zostaje nietknięta.
    assert source.count("updated_by IS NULL") == 2


def test_signature_recovery_uses_migration_only_when_policy_is_missing() -> None:
    entrypoint = (BACKEND_ROOT / "entrypoint.sh").read_text()
    assert "python -m app.services.signature_policy_bootstrap" in entrypoint
    block = (BACKEND_ROOT / "app/services/signature_policy_bootstrap.py").read_text()
    assert "0282_b2b_signature_permission.py" in block
    assert "if not ready:" in block
    assert "pg_get_constraintdef(oid)" in block
    assert "migration.upgrade()" in block
    assert "FOR UPDATE" in block
