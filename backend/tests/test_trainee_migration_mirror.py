"""Praktykant (0372): lustro migracji w entrypoint.sh i rejestracje.

Prod alembic bywa osierocony — entrypoint JEST wdrożeniem schematu.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.job_proposal import JOB_PROPOSAL_SOURCES
from app.models.user import UserRole

ROOT = Path(__file__).resolve().parents[1]


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def _migration() -> dict:
    ns: dict = {}
    source = (ROOT / "alembic/versions/0372_trainee_call_lists.py").read_text()
    exec(compile(source.replace("from alembic import op", ""), "m", "exec"), ns)
    return ns


def test_tables_columns_and_indexes_are_mirrored() -> None:
    ns = _migration()
    entry = _squash((ROOT / "entrypoint.sh").read_text())
    for ddl in (ns["CREATE_PROGRAMS"], ns["CREATE_LISTS"], ns["CREATE_ITEMS"]):
        assert _squash(ddl) in entry, ddl.splitlines()[0]
    for statement in (*ns["CANDIDATE_COLUMNS"], *ns["INDEXES"]):
        assert _squash(statement) in entry, statement
    for name, _ in ns["CANDIDATE_CHECKS"]:
        assert f"ADD CONSTRAINT {name}" in entry


def test_enums_role_checks_and_proposal_source_are_mirrored() -> None:
    entry = (ROOT / "entrypoint.sh").read_text()
    assert "ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'trainee'" in entry
    assert (
        "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'trainee_program_decision'"
        in entry
    )
    for name in (
        "ck_rbac_role_section_permissions_role",
        "ck_rbac_role_action_permissions_role",
        "ck_users_exclusive_finance_viewer_roles",
    ):
        assert f"conname = '{name}'" in entry
    assert "'reassign', 'trainee'" in entry
    assert "trainee" in JOB_PROPOSAL_SOURCES
    # Rozszerzenie CHECK-ów ról musi iść PRZED seedem macierzy (dane wstawiają
    # wiersze `trainee`), czyli w `_COLUMN_STATEMENTS`, nie w `_CONSTRAINT_…`.
    columns = entry.index("_COLUMN_STATEMENTS = [")
    data = entry.index("_DATA_STATEMENTS = [")
    widen = entry.index("conname = 'ck_rbac_role_section_permissions_role'")
    assert columns < widen < data


def test_role_is_exclusive_everywhere() -> None:
    user_model = (ROOT / "app/models/user.py").read_text()
    assert "WHEN role::text IN ('finance', 'user', 'trainee')" in user_model
    assert UserRole.trainee.value == "trainee"


def test_tables_are_probed_by_deep_health() -> None:
    main = (ROOT / "app/main.py").read_text()
    for table in ("trainee_programs", "trainee_call_lists", "trainee_call_items"):
        assert f'("{table}",' in main


def test_call_items_cascade_with_the_candidate() -> None:
    ns = _migration()
    assert (
        "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE"
        in _squash(ns["CREATE_ITEMS"])
    )
