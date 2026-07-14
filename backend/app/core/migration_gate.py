"""Read-only database revision gate shared by Uvicorn and the container CLI."""

from __future__ import annotations

import os

import asyncpg
from alembic.config import Config
from alembic.script import ScriptDirectory


def database_url() -> str:
    value = os.environ.get("DATABASE_URL", "")
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value.replace("postgresql+asyncpg://", "postgresql://", 1)


def expected_head() -> str:
    config_path = os.environ.get("NEXUS_ALEMBIC_CONFIG", "alembic/alembic.ini")
    heads = ScriptDirectory.from_config(Config(config_path)).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"expected exactly one Alembic head, found {len(heads)}")
    return heads[0]


async def applied_heads(url: str) -> set[str]:
    connection = await asyncpg.connect(url)
    try:
        exists = await connection.fetchval(
            "SELECT to_regclass('public.alembic_version') IS NOT NULL"
        )
        if not exists:
            return set()
        rows = await connection.fetch("SELECT version_num FROM alembic_version")
        return {str(row["version_num"]) for row in rows}
    finally:
        await connection.close()


async def require_current_migration_head() -> None:
    expected = expected_head()
    applied = await applied_heads(database_url())
    if applied != {expected}:
        actual = ", ".join(sorted(applied)) if applied else "none"
        raise RuntimeError(
            f"database is not at repository head (expected {expected}, applied {actual})"
        )
