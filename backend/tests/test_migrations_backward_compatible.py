"""Etap B2: migracja musi działać ze starym kodem na nowym schemacie.

Przy rolling update stary kontener obsługuje ruch w trakcie `alembic upgrade`
nowego, więc usunięcie albo zmiana nazwy kolumny idzie w kolejnym wdrożeniu
po kodzie, który jej nie czyta. → docs/claude/podstawy/migracje-zgodne-wstecz.md
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"
# Migracje sprzed reguły (13.11.2026) i te w otwartych PR-ach tego dnia.
FIRST_CHECKED = 692
MARKER = re.compile(r"^\s*# zgodne-wstecz: \S.{10,}", re.MULTILINE)

_DESTRUCTIVE_SQL = re.compile(
    r"\bDROP\s+(COLUMN|TABLE)\b"
    r"|\bRENAME\s+(COLUMN|TO)\b"
    r"|\bALTER\s+COLUMN\s+\S+\s+(SET\s+DATA\s+)?TYPE\b"
    r"|\bSET\s+NOT\s+NULL\b",
    re.IGNORECASE,
)
_DESTRUCTIVE_OPS = {"drop_column", "drop_table", "rename_table"}


def _destructive_steps(source: str) -> list[str]:
    tree = ast.parse(source)
    upgrade = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "upgrade"
        ),
        None,
    )
    if upgrade is None:
        return []
    found = []
    for node in ast.walk(upgrade):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            name = node.func.attr
            keywords = {kw.arg for kw in node.keywords}
            if name in _DESTRUCTIVE_OPS:
                found.append(f"op.{name}")
            elif name == "alter_column" and keywords & {"new_column_name", "type_"}:
                found.append("op.alter_column (nazwa albo typ)")
            elif name == "alter_column" and any(
                kw.arg == "nullable"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is False
                for kw in node.keywords
            ):
                found.append("op.alter_column(nullable=False)")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            match = _DESTRUCTIVE_SQL.search(node.value)
            if match:
                found.append(match.group(0))
    return found


def _checked_migrations() -> list[Path]:
    paths = []
    for path in sorted(VERSIONS.glob("*.py")):
        number = re.match(r"(\d{4})_", path.name)
        if number and int(number.group(1)) >= FIRST_CHECKED:
            paths.append(path)
    return paths


@pytest.mark.parametrize("path", _checked_migrations(), ids=lambda p: p.name)
def test_destructive_migration_names_its_backward_compatibility(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    steps = _destructive_steps(source)
    assert not steps or MARKER.search(source), (
        f"{path.name}: {', '.join(steps)} w upgrade() bez linii "
        "`# zgodne-wstecz: <PR, po którym kod nie czyta tej kolumny>`. "
        "Przy rolling update stary kod chodzi na nowym schemacie: najpierw kod, "
        "usunięcie w kolejnym wdrożeniu (docs/claude/podstawy/migracje-zgodne-wstecz.md)."
    )


def test_new_migrations_have_a_number() -> None:
    """Strażnik wybiera migracje po numerze, więc plik bez numeru by go ominął."""
    unnumbered = sorted(
        p.name
        for p in VERSIONS.glob("*.py")
        if not re.match(r"\d{4}_", p.name) and p.name != "__init__.py"
    )
    assert unnumbered == ["wyroznienia_availability.py"]


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ('op.drop_column("users", "x")', ["op.drop_column"]),
        ('op.execute("ALTER TABLE users DROP COLUMN IF EXISTS x")', ["DROP COLUMN"]),
        ('op.execute("ALTER TABLE users RENAME COLUMN a TO b")', ["RENAME COLUMN"]),
        (
            'op.alter_column("users", "a", new_column_name="b")',
            ["op.alter_column (nazwa albo typ)"],
        ),
        (
            'op.alter_column("users", "a", nullable=False)',
            ["op.alter_column(nullable=False)"],
        ),
        (
            'op.execute("ALTER TABLE users ALTER COLUMN a TYPE text")',
            ["ALTER COLUMN a TYPE"],
        ),
        (
            'op.execute("ALTER TABLE users ALTER COLUMN a SET NOT NULL")',
            ["SET NOT NULL"],
        ),
        ('op.add_column("users", sa.Column("x", sa.Integer()))', []),
        ('op.execute("CREATE INDEX CONCURRENTLY ix ON users (x)")', []),
    ],
)
def test_detector(body: str, expected: list[str]) -> None:
    source = f"def upgrade():\n    {body}\n\n\ndef downgrade():\n    op.drop_column('u', 'x')\n"
    assert _destructive_steps(source) == expected
