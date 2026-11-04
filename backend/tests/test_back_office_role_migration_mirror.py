"""Rola „Back office” (0645): lustro migracji w entrypoint.sh i modelach.

Bez poszerzonych CHECK-ów zasiew macierzy przy starcie wywróciłby się na
wierszu ``back_office``, a bez wyłączności drugie konto dałoby tej osobie sekcję
Finanse z innej roli.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.models.section_permission import RoleActionPermission, RoleSectionPermission
from app.models.user import User, UserRole
from app.services import back_office_role_schema as schema
from app.services import hr_schema_bundle as bundle
from app.services import permission_catalog as catalog

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "0645_back_office_role.py"


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _check_sql(model, name: str) -> str:
    for constraint in model.__table__.constraints:
        if constraint.name == name:
            return str(constraint.sqltext)
    raise AssertionError(f"{model.__name__} nie ma {name}")


def test_migration_reads_the_shared_schema_and_follows_main_head() -> None:
    spec = importlib.util.spec_from_file_location("m0645", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0645_back_office_role"
    assert module.down_revision == "0644_client_contracts_view_permission"
    assert module.schema is schema


def test_enum_value_is_literal_in_entrypoint_enum_phase() -> None:
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    enum_block = entry[entry.index("_ENUM_STATEMENTS = [") :]
    enum_block = enum_block[: enum_block.index("\n]")]
    assert schema.ENUM_DDL in bundle.ENUM_DDL
    assert f'"{schema.ENUM_DDL}"' in enum_block


def test_role_checks_widen_after_board_and_before_the_seed() -> None:
    columns = list(bundle.COLUMN_DDL)
    board_exclusive = next(
        i for i, s in enumerate(columns) if "LIKE '%''board''%'" in s and "users" in s
    )
    for statement in schema.ROLE_CHECK_DDL:
        assert columns.index(statement) > board_exclusive
    for statement in schema.SEED_DDL:
        assert statement in bundle.DATA_DDL
    assert schema.EXCLUSIVE_ROLES_CHECK in schema.EXCLUSIVE_CHECK_BLOCK
    assert "LIKE '%''back_office''%'" in schema.EXCLUSIVE_CHECK_BLOCK


def test_empty_matrix_seed_in_entrypoint_knows_the_role() -> None:
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert "('back_office', 'insights', 'read')" in entry
    assert "('back_office', 'b2b_contract_generator', 'manage')" in entry


def test_models_know_the_role() -> None:
    for model, name in (
        (RoleSectionPermission, "ck_rbac_role_section_permissions_role"),
        (RoleActionPermission, "ck_rbac_role_action_permissions_role"),
    ):
        assert "'back_office'" in _check_sql(model, name)
    exclusive = _check_sql(User, "ck_users_exclusive_finance_viewer_roles")
    assert _squash(exclusive) == _squash(schema.EXCLUSIVE_ROLES_CHECK)
    assert UserRole.back_office.value == "back_office"
    assert "back_office" in catalog.ROLES


def test_back_office_role_cannot_be_combined() -> None:
    user = User(
        role=UserRole.back_office,
        roles=[UserRole.back_office.value, UserRole.recruiter.value],
    )
    try:
        user.ensure_exclusive_roles()
    except ValueError as exc:
        assert "back_office" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("rola back_office połączyła się z rekruterem")


def test_orders_permission_reaches_both_action_checks_in_entrypoint() -> None:
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert entry.count("'client_contracts_view', 'orders_work')") == 2
