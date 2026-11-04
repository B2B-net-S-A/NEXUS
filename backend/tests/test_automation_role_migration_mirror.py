"""Rola „Automatyzacje” (0446): lustro migracji w entrypoint.sh i rejestracje.

Prod alembic bywa osierocony — entrypoint JEST wdrożeniem schematu. Bez
poszerzonych CHECK-ów zasiew macierzy przy starcie wywróciłby się na wierszu
``automation``, a bez wyłączności konto dało by się połączyć z rekruterem.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.section_permission import RoleActionPermission, RoleSectionPermission
from app.models.user import User, UserRole
from app.services import permission_catalog as catalog
from app.services.action_permissions import (
    DEFAULT_ROLE_ACTION_ACCESS,
    UNGRANTABLE_ROLES,
    ActionAccess,
    ProductAction,
)
from app.services.section_permissions import (
    DEFAULT_ROLE_SECTION_ACCESS,
    ProductSection,
    SectionAccess,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "alembic/versions/0446_automation_role.py"


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _migration() -> dict:
    ns: dict = {}
    source = MIGRATION.read_text(encoding="utf-8")
    exec(compile(source.replace("from alembic import op", ""), "m", "exec"), ns)
    return ns


def _check_sql(model, name: str) -> str:
    for constraint in model.__table__.constraints:
        if constraint.name == name:
            return _squash(str(constraint.sqltext))
    raise AssertionError(f"{model.__name__} nie ma {name}")


def test_enum_checks_and_seeds_are_mirrored_in_entrypoint() -> None:
    ns = _migration()
    entry = _squash((ROOT / "entrypoint.sh").read_text(encoding="utf-8"))
    assert "ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'automation'" in entry
    assert _squash(ns["SEED_SECTIONS"]) in entry
    assert _squash(ns["SEED_ACTIONS"]) in entry
    assert f"CHECK (role IN ({ns['ROLE_VALUES']}))" in entry
    assert f"CHECK ({_squash(ns['EXCLUSIVE_ROLES_CHECK'])}) NOT VALID" in entry


def test_role_checks_are_widened_before_the_matrix_seed() -> None:
    entry = (ROOT / "entrypoint.sh").read_text(encoding="utf-8")
    columns = entry.index("_COLUMN_STATEMENTS = [")
    data = entry.index("_DATA_STATEMENTS = [")
    widen = entry.index("LIKE '%automation%'")
    seed = entry.index("SELECT 'automation', s.section, s.access")
    assert columns < widen < data < seed


def test_models_know_the_role() -> None:
    ns = _migration()
    for model, name in (
        (RoleSectionPermission, "ck_rbac_role_section_permissions_role"),
        (RoleActionPermission, "ck_rbac_role_action_permissions_role"),
    ):
        assert "'automation'" in _check_sql(model, name)
    exclusive = _check_sql(User, "ck_users_exclusive_finance_viewer_roles")
    # Od 0456 („Ludzie w NEXUSIE”) wyrażenie zna też rolę „Pracownik” — model
    # równa się wersji z ``hr_access_schema`` (test lustra 0456); tu pilnujemy,
    # że „Automatyzacje” dalej są w obu połówkach wyłączności.
    assert "role::text IN ('finance', 'user', 'trainee', 'automation'" in exclusive
    assert "ARRAY['finance', 'user', 'trainee', 'automation'" in exclusive
    assert ns["EXCLUSIVE_ROLES_CHECK"].startswith("CASE WHEN role::text IN")
    assert UserRole.automation.value == "automation"


def test_role_reads_only_and_accepts_grants() -> None:
    sections = DEFAULT_ROLE_SECTION_ACCESS[UserRole.automation]
    assert max(sections.values()) == SectionAccess.read
    assert sections[ProductSection.finance] is SectionAccess.none
    assert sections[ProductSection.system_admin] is SectionAccess.none

    actions = DEFAULT_ROLE_ACTION_ACCESS[UserRole.automation]
    granted = {
        action for action, access in actions.items() if access > ActionAccess.none
    }
    assert granted == {ProductAction.delivery_view}
    assert "automation" in catalog.ROLES
    assert UserRole.automation not in UNGRANTABLE_ROLES


def test_role_cannot_be_combined() -> None:
    user = User(
        role=UserRole.automation,
        roles=[UserRole.automation.value, UserRole.recruiter.value],
    )
    try:
        user.ensure_exclusive_roles()
    except ValueError as exc:
        assert "automation" in str(exc)
    else:  # pragma: no cover - czytelny komunikat zamiast cichego przejścia
        raise AssertionError("rola automation połączyła się z rekruterem")


def test_named_permissions_migration_seeds_only_roles_known_at_0410() -> None:
    """Na świeżej bazie 0410 biegnie przed 0446 — wiersz ``automation`` złamałby
    CHECK ról tabeli akcji (pełne CI 14.10.2026). Rolę zasiewa 0446 i siatka
    przy starcie."""
    import importlib.util

    from app.services import permission_schema as schema

    path = ROOT / "alembic/versions/0410_named_permissions.py"
    spec = importlib.util.spec_from_file_location("named_permissions_0410", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    assert "automation" not in migration.ROLES_AT_0410
    # „Ludzie w NEXUSIE” (0455) dokłada rolę „Pracownik”, a 0490 „Radę
    # nadzorczą” — obie po 0410.
    assert set(migration.ROLES_AT_0410) | {"automation", "employee", "board"} == set(
        catalog.ROLES
    )
    frozen = schema.seed_sql(migration.ROLES_AT_0410)
    assert "('automation')" not in frozen
    assert "('automation')" in schema.SEED_SQL
