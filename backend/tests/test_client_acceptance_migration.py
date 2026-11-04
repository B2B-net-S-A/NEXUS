"""0451: „Klient zaakceptował” — kolumny dat na wierszu etapu i typ dzwonka
mają lustro w entrypoincie (prod alembic bywa osierocony), a downgrade
odmawia, zanim stary kod trafi na wpis, którego nie odczyta."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0451_client_acceptance.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0451", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_has_a_parent_and_its_own_revision() -> None:
    module = _migration_module()
    assert module.revision == "0451_client_acceptance"
    assert module.down_revision and module.down_revision != module.revision


def test_entrypoint_mirrors_every_statement() -> None:
    module = _migration_module()
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    assert f"'{NotificationType.client_accepted.value}'" in module.ADD_NOTIFICATION_TYPE
    for statement in (
        module.ADD_NOTIFICATION_TYPE,
        module.ADD_ACCEPTED_ON,
        module.ADD_PLANNED_START,
    ):
        assert statement in entrypoint


def test_model_columns_match_the_migration() -> None:
    module = _migration_module()
    columns = CandidateStage.__table__.columns
    for name, statement in (
        ("client_accepted_on", module.ADD_ACCEPTED_ON),
        ("planned_start_on", module.ADD_PLANNED_START),
    ):
        assert name in columns
        assert columns[name].nullable
        assert f"{name} DATE NULL" in statement


def test_upgrade_adds_the_enum_value_outside_a_transaction() -> None:
    source = MIGRATION.read_text()
    upgrade = source[source.index("def upgrade") : source.index("def downgrade")]
    assert "autocommit_block()" in upgrade
    assert "op.execute(ADD_NOTIFICATION_TYPE)" in upgrade


def test_downgrade_refuses_with_live_bells_before_dropping(monkeypatch) -> None:
    module = _migration_module()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    module.downgrade()
    assert executed[0] == module.REFUSE_WITH_LIVE_ROWS
    assert "RAISE EXCEPTION 'Downgrade 0451 odmawia" in executed[0]
    assert "notification_type::text = 'client_accepted'" in executed[0]
    assert any("DROP COLUMN IF EXISTS client_accepted_on" in s for s in executed[1:])
