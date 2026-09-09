"""Hosted PostgreSQL check of the real entrypoint fallback, without containers locally."""

import ast
from pathlib import Path
import uuid

from sqlalchemy import text

from app.core.database import AsyncSessionLocal


def startup_statements():
    script = (Path(__file__).parents[1] / "entrypoint.sh").read_text()
    block = (
        script.split("python - <<'PY'", 1)[1].split("\n", 1)[1].split("\nPY\n", 1)[0]
    )
    statements = []
    for node in ast.parse(block).body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List):
            continue
        if not any(
            isinstance(target, ast.Name)
            and target.id in {"_COLUMN_STATEMENTS", "_DATA_STATEMENTS"}
            for target in node.targets
        ):
            continue
        for value in node.value.elts:
            try:
                sql = ast.literal_eval(value)
            except ValueError:
                continue
            if any(
                token in sql
                for token in (
                    "ALTER TABLE clients ADD COLUMN IF NOT EXISTS cv_rule_edit_revision",
                    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS draft_payload",
                    "ALTER TABLE client_cv_rules ADD COLUMN IF NOT EXISTS edit_revision",
                    "ALTER TABLE client_cv_rule_previews ADD COLUMN IF NOT EXISTS recipe_snapshot",
                    "CREATE TABLE IF NOT EXISTS client_cv_rule_publications",
                    "0283_cv_publications_seeded",
                )
            ):
                statements.append(sql)
    assert len(statements) == 6
    return statements


async def test_startup_fallback_is_idempotent_and_preserves_publications():
    schema = "cv_startup_" + uuid.uuid4().hex
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            await db.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            for sql in (
                "CREATE TABLE clients (id INTEGER PRIMARY KEY, cv_content_mode_cap TEXT, cv_interactive_enabled BOOLEAN)",
                "CREATE TABLE users (id INTEGER PRIMARY KEY)",
                "CREATE TABLE client_cv_rule_previews (id INTEGER PRIMARY KEY)",
                "CREATE TABLE app_settings (key TEXT PRIMARY KEY, value JSONB)",
                "CREATE TABLE client_cv_rules (client_id INTEGER PRIMARY KEY, version INTEGER, confirmed_at TIMESTAMPTZ, confirmed_by INTEGER, cv_language TEXT)",
                "INSERT INTO clients VALUES (1, 'basic', false), (2, 'polished', true)",
                "INSERT INTO users VALUES (1)",
                "INSERT INTO client_cv_rules VALUES (1, 3, now(), 1, 'pl'), (2, 1, NULL, NULL, 'en')",
            ):
                await db.execute(text(sql))
            statements = startup_statements()
            for sql in statements:
                await db.execute(text(sql))
            original = (
                await db.execute(
                    text(
                        "SELECT recipe FROM client_cv_rule_publications WHERE client_id=1"
                    )
                )
            ).scalar_one()
            assert original["cv_language"] == "pl"
            assert original["cv_interactive_enabled"] is False
            assert (
                await db.scalar(
                    text("SELECT count(*) FROM client_cv_rule_publications")
                )
                == 1
            )
            await db.execute(
                text("UPDATE client_cv_rules SET cv_language='en' WHERE client_id=1")
            )
            await db.execute(
                text("UPDATE clients SET cv_rule_edit_revision=9 WHERE id=1")
            )
            for sql in statements:
                await db.execute(text(sql))
            assert (
                await db.execute(
                    text(
                        "SELECT recipe FROM client_cv_rule_publications WHERE client_id=1"
                    )
                )
            ).scalar_one() == original
            assert (
                await db.scalar(
                    text("SELECT cv_rule_edit_revision FROM clients WHERE id=1")
                )
                == 9
            )
            assert await db.scalar(text("SELECT count(*) FROM app_settings")) == 1
        finally:
            await db.rollback()  # Includes CREATE SCHEMA and all test rows.
