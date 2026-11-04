"""Role `sourcer` i `tac` są wycofane (0411) — strażnik i przypięcie enuma.

W `UserRole` zostały jako ALIASY rekrutera wyłącznie po to, żeby wiersz ze
starą etykietą dał się odczytać. Alias użyty w kodzie jest pułapką: w słowniku
po cichu nadpisuje wpis rekrutera (wygrywa ostatni klucz), a w zbiorze ról
niczego nie dodaje — dlatego żaden plik nie może po niego sięgać.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from pydantic import TypeAdapter
from sqlalchemy.dialects import postgresql

from app.models.kpi_target import KpiRoleDefault
from app.models.user import User, UserRole, known_roles
from app.services.role_merge import RETIRED_ROLE_VALUES

BACKEND = Path(__file__).resolve().parents[1]
_SCANNED = ("app", "tests", "scripts", "seed.py")


def _python_files() -> list[Path]:
    files: list[Path] = []
    for entry in _SCANNED:
        path = BACKEND / entry
        files.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    return files


def _retired_role_uses(tree: ast.AST) -> list[int]:
    lines = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.attr not in RETIRED_ROLE_VALUES:
            continue
        owner = node.value
        name = owner.id if isinstance(owner, ast.Name) else getattr(owner, "attr", "")
        if name == "UserRole":
            lines.append(node.lineno)
    return lines


def test_no_code_reaches_for_a_retired_role() -> None:
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(
            f"{path.relative_to(BACKEND)}:{line}" for line in _retired_role_uses(tree)
        )
    assert not offenders, (
        "Rola sourcer/TAC nie istnieje od 0411 — użyj UserRole.recruiter:\n"
        + "\n".join(offenders)
    )


def test_retired_roles_are_not_listed_as_roles() -> None:
    names = [role.name for role in UserRole]
    assert "recruiter" in names
    assert not set(names) & set(RETIRED_ROLE_VALUES)
    assert {role.value for role in UserRole}.isdisjoint(RETIRED_ROLE_VALUES)


@pytest.mark.parametrize("column", [User.role, KpiRoleDefault.role])
def test_old_label_in_the_database_reads_as_recruiter(column) -> None:
    dialect = postgresql.dialect()
    read = column.type.result_processor(dialect, None)
    write = column.type.bind_processor(dialect)

    for label in RETIRED_ROLE_VALUES:
        assert read(label) is UserRole.recruiter
    assert write(UserRole.recruiter) == "recruiter"


def test_role_lists_fold_retired_roles_and_drop_unknown_ones() -> None:
    assert known_roles(["delivery_lead", "tac", "recruiter", "sourcer", "nope"]) == [
        UserRole.delivery_lead,
        UserRole.recruiter,
    ]
    assert known_roles(None) == []

    lead = User(role=UserRole.delivery_lead, roles=["delivery_lead", "tac"])
    assert lead.get_all_roles() == {UserRole.delivery_lead, UserRole.recruiter}
    # `has_role` i `get_all_roles` odpowiadają tak samo na starą etykietę.
    assert lead.has_role(UserRole.recruiter)
    assert lead.has_role("tac")
    assert not lead.has_role(UserRole.finance)


def test_openapi_lists_each_role_once() -> None:
    """Pydantic buduje `enum` z `__members__` — aliasy nie mogą się tam powtarzać."""

    listed = TypeAdapter(UserRole).json_schema()["enum"]
    assert listed == [role.value for role in UserRole]
    assert not set(listed) & set(RETIRED_ROLE_VALUES)
