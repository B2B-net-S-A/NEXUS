"""0641: kanały linków w źródłach mają lustro w entrypoincie."""

from __future__ import annotations

from pathlib import Path

from app.models.candidate_source_event import CHANNEL_LABELS, SourceChannel
from app.services import career_link_channels_schema as schema

BACKEND = Path(__file__).resolve().parents[1]


def test_entrypoint_mirrors_enum_and_backfill() -> None:
    entry = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    for stmt in schema.ENUM_DDL:
        assert stmt in entry
    assert "_career_link_channels_schema.BACKFILL_DDL" in entry
    assert "*_CAREER_LINK_CHANNELS_BACKFILL," in entry


def test_migration_runs_enum_outside_a_transaction() -> None:
    migration = (BACKEND / "alembic/versions/0641_career_link_channels.py").read_text(
        encoding="utf-8"
    )
    assert "autocommit_block" in migration
    assert "schema.ENUM_DDL" in migration and "schema.BACKFILL_DDL" in migration


def test_channels_have_labels() -> None:
    assert SourceChannel.career_link_general in CHANNEL_LABELS
    assert SourceChannel.career_link_job in CHANNEL_LABELS
