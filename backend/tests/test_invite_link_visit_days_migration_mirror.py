"""0640: dzienne wejścia na linki mają lustro w entrypoincie i sondę w health/deep."""

from __future__ import annotations

from pathlib import Path

from app.services import invite_link_visits_schema as schema

BACKEND = Path(__file__).resolve().parents[1]


def test_migration_reads_the_shared_ddl() -> None:
    migration = (BACKEND / "alembic/versions/0640_invite_link_visit_days.py").read_text(
        encoding="utf-8"
    )
    assert "for stmt in schema.TABLE_DDL:" in migration


def test_entrypoint_mirrors_the_ddl() -> None:
    entry = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert "_invite_link_visits_schema.TABLE_DDL" in entry
    assert entry.count("_INVITE_LINK_VISITS_DDL") >= 3, (
        "lista musi być użyta w fazie DDL"
    )


def test_every_statement_is_idempotent() -> None:
    assert all("IF NOT EXISTS" in stmt for stmt in schema.TABLE_DDL)


def test_deep_health_probes_the_table() -> None:
    main = (BACKEND / "app/main.py").read_text(encoding="utf-8")
    assert '("candidate_invite_link_visit_days", CandidateInviteLinkVisitDay)' in main
