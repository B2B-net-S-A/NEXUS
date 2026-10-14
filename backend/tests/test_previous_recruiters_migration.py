"""0446: „Poprzedni rekruter” — tabela i dwa typy dzwonków mają lustro
w entrypoincie (prod alembic bywa osierocony), model zgadza się z DDL,
a downgrade odmawia, zanim stary kod trafi na dzwonek, którego nie odczyta."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.models.notification import NotificationType

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0446_job_previous_recruiters.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0446", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_migration_has_a_parent_and_its_own_revision() -> None:
    # Rodzica nie przypinamy nazwą — łańcuch pilnuje test pojedynczego heada.
    module = _migration_module()
    assert module.revision == "0446_job_previous_recruiters"
    assert module.down_revision and module.down_revision != module.revision


def test_table_and_indexes_are_mirrored_in_the_entrypoint() -> None:
    module = _migration_module()
    # Entrypoint skleja długie polecenia z sąsiednich literałów ("…" "…").
    entry = _squash(re.sub(r'"\s+"', "", (BACKEND / "entrypoint.sh").read_text()))
    for statement in (
        module.CREATE_TABLE,
        module.CREATE_JOB_INDEX,
        module.CREATE_OPEN_INDEX,
        module.CREATE_USER_OPEN_INDEX,
        module.ADD_PARKED_TYPE,
        module.ADD_RESTORED_TYPE,
    ):
        assert _squash(statement) in entry, statement


def test_model_matches_the_table() -> None:
    from app.models.job_previous_recruiter import JobPreviousRecruiter

    module = _migration_module()
    columns = set(JobPreviousRecruiter.__table__.columns.keys())
    ddl = re.findall(r"^\s{4}([a-z_]+) [A-Z]", module.CREATE_TABLE, flags=re.M)
    assert set(ddl) == columns
    constraints = {c.name for c in JobPreviousRecruiter.__table__.constraints}
    for name in re.findall(r"CONSTRAINT (ck_[a-z_]+)", module.CREATE_TABLE):
        assert name in constraints, name
    indexes = {index.name for index in JobPreviousRecruiter.__table__.indexes}
    assert {
        "ix_job_previous_recruiters_job_id",
        "ux_job_previous_recruiters_open",
        "ix_job_previous_recruiters_user_open",
    } <= indexes


def test_enum_values_match_the_model() -> None:
    module = _migration_module()
    assert f"'{NotificationType.recruiter_parked.value}'" in module.ADD_PARKED_TYPE
    assert f"'{NotificationType.recruiter_restored.value}'" in module.ADD_RESTORED_TYPE
    source = MIGRATION.read_text()
    upgrade = source[source.index("def upgrade") : source.index("def downgrade")]
    # ``ALTER TYPE … ADD VALUE`` nie może żyć w transakcji migracji.
    assert "autocommit_block()" in upgrade


def test_downgrade_refuses_while_such_bells_exist(monkeypatch) -> None:
    module = _migration_module()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    module.downgrade()
    assert executed[0] == module.REFUSE_WITH_LIVE_ROWS
    assert "RAISE EXCEPTION 'Downgrade 0446 odmawia" in executed[0]
    assert "recruiter_parked" in executed[0] and "recruiter_restored" in executed[0]
