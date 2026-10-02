"""0409: typ powiadomienia o propozycjach przydziału ma lustro w entrypoincie
(prod alembic bywa osierocony), a downgrade odmawia, zanim stary kod trafi na
wpis, którego nie odczyta."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.models.notification import NotificationType

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0409_request_allocation_proposals.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0408", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_chains_after_onsite_days_per_month() -> None:
    module = _migration_module()
    assert module.revision == "0409_request_allocation_proposals"
    assert module.down_revision == "0408_board_task_waiting_notif"


def test_entrypoint_adds_the_same_enum_value_as_the_migration() -> None:
    module = _migration_module()
    value = NotificationType.request_allocation_proposals.value
    assert f"'{value}'" in module.ADD_NOTIFICATION_TYPE
    assert module.ADD_NOTIFICATION_TYPE in (BACKEND / "entrypoint.sh").read_text()


def test_upgrade_adds_the_value_outside_a_transaction() -> None:
    # ``ALTER TYPE … ADD VALUE`` nie może żyć w transakcji migracji.
    module = _migration_module()
    source = MIGRATION.read_text()
    upgrade = source[source.index("def upgrade") : source.index("def downgrade")]
    assert "autocommit_block()" in upgrade
    assert "op.execute(ADD_NOTIFICATION_TYPE)" in upgrade
    assert "ADD VALUE IF NOT EXISTS" in module.ADD_NOTIFICATION_TYPE


def test_downgrade_only_refuses_when_such_notifications_exist(monkeypatch) -> None:
    module = _migration_module()
    executed: list[str] = []
    monkeypatch.setattr(module.op, "execute", executed.append, raising=False)
    module.downgrade()
    assert executed == [module.REFUSE_WITH_LIVE_ROWS]
    guard = executed[0]
    assert "RAISE EXCEPTION 'Downgrade 0409 odmawia" in guard
    assert "notification_type::text = 'request_allocation_proposals'" in guard
    # Wartość enuma zostaje (Postgres nie ma DROP VALUE) i nic nie jest kasowane.
    assert "DROP" not in guard and "DELETE" not in guard
