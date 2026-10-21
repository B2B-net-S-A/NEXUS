"""Rola „Rada nadzorcza” (0490): lustro migracji w entrypoint.sh i modelach.

Bez poszerzonych CHECK-ów zasiew macierzy przy starcie wywróciłby się na
wierszu ``board``, a bez wyłączności konto Rady dałoby się połączyć z rolą,
która zapisuje.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.models.section_permission import RoleActionPermission, RoleSectionPermission
from app.models.user import User, UserRole
from app.services import board_role_schema as schema
from app.services import hr_schema_bundle as bundle
from app.services import permission_catalog as catalog

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic" / "versions" / "0490_board_role.py"


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _check_sql(model, name: str) -> str:
    for constraint in model.__table__.constraints:
        if constraint.name == name:
            return str(constraint.sqltext)
    raise AssertionError(f"{model.__name__} nie ma {name}")


def test_migration_reads_the_shared_schema_and_follows_main_head() -> None:
    spec = importlib.util.spec_from_file_location("m0490", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0490_board_role"
    assert module.down_revision == "0489_career_recruiter_about"
    assert module.schema is schema


def test_enum_value_is_literal_in_entrypoint_enum_phase() -> None:
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    enum_block = entry[entry.index("_ENUM_STATEMENTS = [") :]
    enum_block = enum_block[: enum_block.index("\n]")]
    assert schema.ENUM_DDL in bundle.ENUM_DDL
    assert f'"{schema.ENUM_DDL}"' in enum_block


def test_role_checks_widen_after_employee_and_before_the_seed() -> None:
    columns = list(bundle.COLUMN_DDL)
    employee_exclusive = next(
        i for i, s in enumerate(columns) if "LIKE '%employee%'" in s and "users" in s
    )
    for statement in schema.ROLE_CHECK_DDL:
        assert columns.index(statement) > employee_exclusive
    for statement in schema.SEED_DDL:
        assert statement in bundle.DATA_DDL
    assert schema.EXCLUSIVE_ROLES_CHECK in schema.EXCLUSIVE_CHECK_BLOCK
    # Znacznik idempotencji nie może trafić w samo „board” wewnątrz innego słowa.
    assert "LIKE '%''board''%'" in schema.EXCLUSIVE_CHECK_BLOCK


def test_empty_matrix_seed_in_entrypoint_knows_the_role() -> None:
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert "('board', 'insights', 'read')" in entry
    assert "('board', 'b2b_contract_generator', 'none')" in entry


def test_models_know_the_role() -> None:
    for model, name in (
        (RoleSectionPermission, "ck_rbac_role_section_permissions_role"),
        (RoleActionPermission, "ck_rbac_role_action_permissions_role"),
    ):
        assert "'board'" in _check_sql(model, name)
    exclusive = _check_sql(User, "ck_users_exclusive_finance_viewer_roles")
    assert _squash(exclusive) == _squash(schema.EXCLUSIVE_ROLES_CHECK)
    assert UserRole.board.value == "board"
    assert "board" in catalog.ROLES


def test_board_role_cannot_be_combined() -> None:
    user = User(
        role=UserRole.board,
        roles=[UserRole.board.value, UserRole.recruiter.value],
    )
    try:
        user.ensure_exclusive_roles()
    except ValueError as exc:
        assert "board" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("rola board połączyła się z rekruterem")


def test_hr_access_migration_seeds_only_roles_known_at_0456() -> None:
    # 0456 biegnie na świeżej bazie przed 0490 — wiersz ``board`` w jej
    # zasiewie łamałby CHECK ról tabeli akcji (CI 21.10.2026).
    spec = importlib.util.spec_from_file_location(
        "m0456", ROOT / "alembic" / "versions" / "0456_hr_access.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "board" not in module.ROLES_AT_0456
    assert set(module.ROLES_AT_0456) | {"board"} == set(catalog.ROLES)
