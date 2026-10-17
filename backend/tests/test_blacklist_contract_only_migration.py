"""0452: kolumny czarnej listy, typ dzwonka i zdjęcie ręcznych wpisów
zatrudnienia mają lustro w entrypoincie (prod alembic bywa osierocony),
a downgrade odmawia, zanim stary kod trafi na wpis, którego nie odczyta."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.models.candidate import Candidate
from app.models.notification import NotificationType

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0452_blacklist_contract_only.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0452", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_has_a_parent_and_its_own_revision() -> None:
    module = _migration_module()
    assert module.revision == "0452_blacklist_contract_only"
    assert module.down_revision == "0451_client_acceptance"


def test_entrypoint_mirrors_every_statement() -> None:
    module = _migration_module()
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    assert (
        f"'{NotificationType.hire_missing_contract.value}'"
        in module.ADD_NOTIFICATION_TYPE
    )
    # Wieloliniowe literały w entrypoincie: porównujemy bez łamania linii.
    flat = entrypoint.replace('"\n    "', "")
    for statement in (
        module.ADD_NOTIFICATION_TYPE,
        module.ADD_BLACKLISTED_AT,
        module.ADD_BLACKLISTED_BY,
        module.ADD_BLACKLIST_REASON,
        module.RETIRE_MANUAL_EMPLOYMENT,
    ):
        assert statement in flat


def test_model_columns_match_the_migration() -> None:
    module = _migration_module()
    columns = Candidate.__table__.columns
    for name, sql_type, statement in (
        ("blacklisted_at", "TIMESTAMPTZ", module.ADD_BLACKLISTED_AT),
        ("blacklisted_by_user_id", "INTEGER", module.ADD_BLACKLISTED_BY),
        ("blacklist_reason", "TEXT", module.ADD_BLACKLIST_REASON),
    ):
        assert name in columns
        assert columns[name].nullable
        assert f"{name} {sql_type} NULL" in statement


def test_manual_employment_retirement_runs_once_and_keeps_history() -> None:
    """Lustro leci przy każdym starcie — marker w tym samym statemencie, a
    wiersze tylko się dezaktywują (z powodem), nic nie jest kasowane."""
    statement = _migration_module().RETIRE_MANUAL_EMPLOYMENT
    assert "ON CONFLICT (key) DO NOTHING RETURNING key" in statement
    assert "EXISTS (SELECT 1 FROM marker)" in statement
    assert "type::text = 'current_employment' AND active" in statement
    assert "deactivation_reason" in statement
    assert "DELETE" not in statement.upper()


def test_upgrade_adds_the_enum_value_outside_a_transaction() -> None:
    source = MIGRATION.read_text()
    upgrade = source[source.index("def upgrade") : source.index("def downgrade")]
    assert "autocommit_block()" in upgrade
    assert "op.execute(ADD_NOTIFICATION_TYPE)" in upgrade
