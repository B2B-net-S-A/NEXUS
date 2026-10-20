"""0482: rozmowa bez Prepu 2 — tabela i typy powiadomień mają lustro
w entrypoincie (prod alembic bywa osierocony), model zgadza się z DDL,
a downgrade odmawia, zanim stary kod trafi na powiadomienie, którego nie
odczyta."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from app.models.notification import NotificationType
from app.models.prep_meeting import PREP2_SKIP_REASONS, Prep2Skip
from app.services.notification_access import NOTIFICATION_SECTION_BY_TYPE
from app.services.notification_categories import NotificationCategory, types_in

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0482_prep2_skips.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0482", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_follows_the_previous_head() -> None:
    module = _migration_module()
    assert module.revision == "0482_prep2_skips"
    assert module.down_revision == "0481_candidate_name_markers_v2"


def test_entrypoint_mirrors_every_statement() -> None:
    module = _migration_module()
    entrypoint = (BACKEND / "entrypoint.sh").read_text()
    for statement in (
        module.CREATE_TABLE,
        module.CREATE_INDEX,
        *module.ADD_NOTIFICATION_TYPES,
    ):
        assert statement in entrypoint, statement[:80]


def test_model_matches_the_migration() -> None:
    module = _migration_module()
    columns = Prep2Skip.__table__.columns
    for name in columns.keys():
        assert f"    {name} " in module.CREATE_TABLE, name
    assert columns["interview_event_id"].unique
    for name in ("reason_note", "call_done_at", "call_done_by", "call_note"):
        assert columns[name].nullable
    for value in PREP2_SKIP_REASONS:
        assert f"'{value}'" in module.CREATE_TABLE


def test_notification_types_live_in_calendar_and_pipeline() -> None:
    module = _migration_module()
    interviews = set(types_in(NotificationCategory.interviews))
    for value in module.NOTIFICATION_TYPES:
        ntype = NotificationType(value)
        assert ntype in interviews
        assert ntype in NOTIFICATION_SECTION_BY_TYPE
        assert f"'{value}'" in module.REFUSE_WITH_LIVE_ROWS


def test_upgrade_adds_enum_values_outside_a_transaction() -> None:
    source = MIGRATION.read_text()
    upgrade = source[source.index("def upgrade") : source.index("def downgrade")]
    assert "autocommit_block()" in upgrade
    assert "ADD_NOTIFICATION_TYPES" in upgrade
