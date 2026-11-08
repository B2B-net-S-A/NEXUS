"""Dwa rozjazdy model ↔ baza z przeglądu B3 (08.11.2026).

``cortex_unmatched_terms.first_seen_at``: migracja 0167 i lustro dodawały
kolumnę bez domyślnej, a backfill 0167 nie zadziałał na produkcji (alembic bywał
osierocony, entrypoint robił tylko ADD COLUMN). Na kopii było 73 935 z 73 935
wierszy z NULL, choć model deklaruje NOT NULL.

``email_attachments.parsed_candidate_id``: baza ma CASCADE (0146), model mówił
SET NULL. Decyzja Artura: zostaje CASCADE, zgodne z usuwaniem danych osobowych.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.models.cortex import CortexUnmatchedTerm
from app.models.m365 import EmailAttachment

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0666_cortex_first_seen_not_null.py"
ADD_COLUMN = (
    "ALTER TABLE cortex_unmatched_terms "
    "ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ"
)


def _migration_module():
    spec = importlib.util.spec_from_file_location("m0665", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_entrypoint_mirrors_the_repair_after_adding_the_column() -> None:
    """Bez lustra produkcja z osieroconym alembikiem zostałaby z NULL-ami."""
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    statement = _migration_module().FILL_AND_REQUIRE_FIRST_SEEN
    assert statement in entrypoint
    assert entrypoint.index(ADD_COLUMN) < entrypoint.index(statement)


def test_model_declares_what_the_repair_leaves_in_the_database() -> None:
    column = CortexUnmatchedTerm.__table__.c.first_seen_at
    assert column.nullable is False
    assert column.server_default is not None


def test_attachment_fk_matches_the_cascade_in_the_database() -> None:
    fks = list(EmailAttachment.__table__.c.parsed_candidate_id.foreign_keys)
    assert [fk.ondelete for fk in fks] == ["CASCADE"]


@pytest.mark.asyncio
async def test_repair_fills_nulls_sets_default_and_can_run_on_every_boot() -> None:
    """Prawdziwy Postgres: kształt tabeli z 0167, NULL-e jak na kopii produkcji."""
    statement = _migration_module().FILL_AND_REQUIRE_FIRST_SEEN
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as conn:
            tx = await conn.begin()
            await conn.execute(text("CREATE SCHEMA first_seen_sandbox"))
            await conn.execute(text("SET LOCAL search_path TO first_seen_sandbox"))
            await conn.execute(
                text(
                    "CREATE TABLE cortex_unmatched_terms ("
                    "id SERIAL PRIMARY KEY, term TEXT NOT NULL, "
                    "last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                    "first_seen_at TIMESTAMPTZ)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO cortex_unmatched_terms (term, last_seen_at) "
                    "VALUES ('kubernetes', '2026-07-12T22:10:59+00:00')"
                )
            )

            await conn.execute(text(statement))
            filled = await conn.scalar(
                text("SELECT first_seen_at = last_seen_at FROM cortex_unmatched_terms")
            )
            nullable, default = (
                await conn.execute(
                    text(
                        "SELECT is_nullable, column_default "
                        "FROM information_schema.columns "
                        "WHERE table_schema = current_schema() "
                        "AND table_name = 'cortex_unmatched_terms' "
                        "AND column_name = 'first_seen_at'"
                    )
                )
            ).one()

            # Nowy wiersz bez kolumny dostaje domyślną, a nie NotNullViolation.
            await conn.execute(
                text("INSERT INTO cortex_unmatched_terms (term) VALUES ('nowy')")
            )
            # Lustro biegnie przy każdym starcie: drugi raz niczego nie zmienia.
            await conn.execute(text(statement))
            nulls = await conn.scalar(
                text(
                    "SELECT count(*) FROM cortex_unmatched_terms "
                    "WHERE first_seen_at IS NULL"
                )
            )
            await tx.rollback()
    finally:
        await engine.dispose()

    assert filled is True
    assert nullable == "NO"
    assert "now()" in default
    assert nulls == 0
