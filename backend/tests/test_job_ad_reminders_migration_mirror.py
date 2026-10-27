"""0526: „nie publikujemy” i typy dzwonka przypomnień o ogłoszeniach mają lustro
w entrypoincie (prod alembic bywa osierocony), sondę w ``/api/health/deep``,
a model zgadza się z DDL."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.models.notification import NotificationType
from app.services import job_ad_reminder_schema as schema

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0526_job_ad_reminders.py"


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0526", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_runs_the_shared_ddl() -> None:
    module = _migration_module()
    assert module.revision == "0526_job_ad_reminders"
    assert module.down_revision == "0525_client_form_score_sheet"
    text = MIGRATION.read_text(encoding="utf-8")
    assert "schema.ALL_DDL" in text
    assert "schema.ENUM_DDL" in text


def test_entrypoint_mirrors_every_statement() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    for statement in (*schema.ALL_DDL, *schema.ENUM_DDL):
        assert statement in entrypoint, statement


def test_ddl_is_idempotent() -> None:
    for statement in (*schema.ALL_DDL, *schema.ENUM_DDL):
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement), statement


def test_enum_values_match_the_model() -> None:
    for value in schema.NOTIFICATION_TYPES:
        assert NotificationType(value).value == value


def test_model_columns_match_the_ddl() -> None:
    from app.models.job_ad_channel_skip import JobAdChannelSkip

    table = schema.TABLE_DDL
    columns = JobAdChannelSkip.__table__.columns
    for column in columns.keys():
        assert re.search(rf"\b{column}\b", table), column
    assert "PRIMARY KEY (job_id, channel)" in table
    assert [c.name for c in JobAdChannelSkip.__table__.primary_key.columns] == [
        "job_id",
        "channel",
    ]
    assert "job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE" in table
    assert "created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL" in table
    for channel in schema.CHANNELS:
        assert f"'{channel}'" in table
        assert len(channel) <= columns["channel"].type.length
    assert columns["reason"].type.length == schema.REASON_MAX


def test_health_deep_probes_the_table_and_model_is_registered() -> None:
    main = (BACKEND / "app" / "main.py").read_text(encoding="utf-8")
    assert '("job_ad_channel_skips", JobAdChannelSkip)' in main
    models = (BACKEND / "app" / "models" / "__init__.py").read_text(encoding="utf-8")
    assert "from app.models.job_ad_channel_skip import JobAdChannelSkip" in models
