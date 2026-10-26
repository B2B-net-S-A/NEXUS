"""0600: uprawnienia „Sprzedaż” — migracja, CHECK w ``entrypoint.sh`` i zasiew."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.services import permission_catalog as catalog
from app.services import permission_schema

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic/versions/0600_sales_permissions.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m0600", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_entrypoint_check_knows_both_sales_permissions() -> None:
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert entry.count(permission_schema.ACTION_CHECK_SQL) == len(
        permission_schema.ACTION_TABLES
    )
    for key in (catalog.SALES_VIEW, catalog.SALES_EDIT):
        assert f"'{key}'" in permission_schema.ACTION_CHECK_SQL


def test_migration_seeds_with_the_roles_known_at_its_time() -> None:
    module = _migration()
    assert set(module.ROLES_AT_0600) <= set(catalog.ROLES)
    assert module.ROLES_AT_0600[0] == catalog.ADMIN


def test_nobody_but_admin_gets_sales_by_default() -> None:
    for role in catalog.ROLES:
        held = catalog.default_permissions_for_role(role)
        if role == catalog.ADMIN:
            assert {catalog.SALES_VIEW, catalog.SALES_EDIT} <= held
        else:
            assert held.isdisjoint({catalog.SALES_VIEW, catalog.SALES_EDIT})
