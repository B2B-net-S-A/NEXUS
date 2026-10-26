"""„Ludzie w NEXUSIE” (0456): rola „Pracownik” i uprawnienia grupy „Ludzie”.

Lustro migracji w entrypoint.sh (przez ``hr_schema_bundle`` + literał enum),
modele i macierze startowe. Bez poszerzonych CHECK-ów zasiew macierzy przy
starcie wywróciłby się na wierszu ``employee``, a bez wyłączności konto
pracownika dałoby się połączyć z rekruterem.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.section_permission import RoleActionPermission, RoleSectionPermission
from app.models.user import User, UserRole
from app.services import hr_access_schema as schema
from app.services import hr_schema_bundle as bundle
from app.services import permission_catalog as catalog
from app.services import permission_schema
from app.services.action_permissions import (
    DEFAULT_ROLE_ACTION_ACCESS,
    UNGRANTABLE_ROLES,
    ActionAccess,
)
from app.services.section_permissions import DEFAULT_ROLE_SECTION_ACCESS, SectionAccess

ROOT = Path(__file__).resolve().parents[1]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _check_sql(model, name: str) -> str:
    for constraint in model.__table__.constraints:
        if constraint.name == name:
            return _squash(str(constraint.sqltext))
    raise AssertionError(f"{model.__name__} nie ma {name}")


def test_enum_value_is_literal_in_entrypoint_enum_phase() -> None:
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    enum_block = entry[entry.index("_ENUM_STATEMENTS = [") :]
    enum_block = enum_block[: enum_block.index("\n]")]
    for statement in bundle.ENUM_DDL:
        assert f'"{statement}"' in enum_block


def test_role_checks_and_seeds_reach_the_entrypoint_phases() -> None:
    for statement in schema.ROLE_CHECK_DDL:
        assert statement in bundle.COLUMN_DDL
    for statement in schema.SEED_DDL:
        assert statement in bundle.DATA_DDL
    assert any(f"role IN ({schema.ROLE_VALUES})" in s for s in schema.ROLE_CHECK_DDL)
    assert schema.EXCLUSIVE_ROLES_CHECK in schema.EXCLUSIVE_CHECK_BLOCK


def test_action_check_literals_in_entrypoint_know_the_new_permissions() -> None:
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    assert entry.count(permission_schema.ACTION_CHECK_SQL) == len(
        permission_schema.ACTION_TABLES
    )
    for action in schema.NEW_ACTIONS:
        assert f"'{action}'" in permission_schema.ACTION_CHECK_SQL
    # Podzbiór, nie równość: późniejsze uprawnienia (Sprzedaż, 0600) dochodzą
    # na końcu katalogu i nie są częścią 0456.
    assert set(schema.PREVIOUS_ACTIONS) | set(schema.NEW_ACTIONS) <= set(
        permission_schema.ACTIONS
    )


def test_models_know_the_role() -> None:
    for model, name in (
        (RoleSectionPermission, "ck_rbac_role_section_permissions_role"),
        (RoleActionPermission, "ck_rbac_role_action_permissions_role"),
    ):
        assert "'employee'" in _check_sql(model, name)
    # Pełną listę wyłącznych ról porównuje lustro najnowszej z nich (0490,
    # ``test_board_role_migration_mirror.py``); tu tylko: ``employee`` w niej jest.
    exclusive = _check_sql(User, "ck_users_exclusive_finance_viewer_roles")
    assert exclusive.count("'employee'") == 2
    assert UserRole.employee.value == "employee"
    assert "employee" in catalog.ROLES


def test_employee_has_no_section_and_no_permission_but_accepts_grants() -> None:
    sections = DEFAULT_ROLE_SECTION_ACCESS[UserRole.employee]
    assert set(sections.values()) == {SectionAccess.none}
    actions = DEFAULT_ROLE_ACTION_ACCESS[UserRole.employee]
    assert set(actions.values()) == {ActionAccess.none}
    # Recepcja z rolą „Pracownik” dostaje „Sprzęt” nadaniem z „Osoby i role”.
    assert UserRole.employee not in UNGRANTABLE_ROLES


def test_employee_role_cannot_be_combined() -> None:
    user = User(
        role=UserRole.employee,
        roles=[UserRole.employee.value, UserRole.recruiter.value],
    )
    try:
        user.ensure_exclusive_roles()
    except ValueError as exc:
        assert "employee" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("rola employee połączyła się z rekruterem")


def test_new_permissions_close_over_nothing_and_admin_holds_them() -> None:
    for key in schema.NEW_ACTIONS:
        assert catalog.close([key]) == {key}
        assert key in catalog.default_permissions_for_role("admin")
    assert catalog.BY_KEY["payroll"].default_roles == ("finance",)
    assert catalog.BY_KEY["cases"].default_roles == ("talent_community_manager",)
    assert catalog.BY_KEY["people_admin"].default_roles == ()
    assert catalog.BY_KEY["equipment"].default_roles == ()
    # Uprawnienia „Ludzi” nie otwierają sekcji Delivery ani Finansów.
    assert catalog.derive_sections(schema.NEW_ACTIONS) == {
        "delivery": "none",
        "finance": "none",
    }
