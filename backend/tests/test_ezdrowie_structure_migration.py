"""Kontrakt migracji 0312/0313 — lustra, bez których zmiana nie dojdzie na produkcję.

Testy czytają PLIKI jako tekst (jak ``test_multi_consultant_orders_migration``):
produkcyjny alembic bywa osierocony, więc każda kolumna, tabela, CHECK i zasiew
musi mieć odbicie w ``entrypoint.sh``, a nowa tabela — sondę w ``/api/health/deep``.
Osobno: zasiew struktury Centrum e-Zdrowia jest idempotentny i działa tylko
przy istniejącym kliencie.
"""

from __future__ import annotations

import ast
import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.ezdrowie_structure import (
    EZDROWIE_STRUCTURE,
    EZDROWIE_STRUCTURE_SEED_SQL,
    build_structure_seed_sql,
)

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION_0312 = BACKEND / "alembic" / "versions" / "0312_ezdrowie_executive_contracts.py"
MIGRATION_0313 = (
    BACKEND / "alembic" / "versions" / "0313_md_optional_scope_and_consumption_status.py"
)
ENTRYPOINT = BACKEND / "entrypoint.sh"
MAIN = BACKEND / "app" / "main.py"

NEW_TABLES = ("client_executive_contracts",)
NEW_COLUMNS = ("project_part", "executive_contract_id", "md_optional_total", "status", "note")
NEW_CHECKS = (
    "ck_client_framework_contracts_project_part",
    "ck_client_executive_contracts_status",
    "ck_client_executive_contracts_number_nonempty",
    "ck_client_orders_md_optional",
    "ck_md_consumptions_status",
)


def _revision_values(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    values: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant):
                    values[target.id] = node.value.value
    return values


def test_migrations_chain_onto_the_single_head():
    first = _revision_values(MIGRATION_0312)
    second = _revision_values(MIGRATION_0313)
    assert first["revision"] == "0312_ezdrowie_executive_contracts"
    assert first["down_revision"] == "0311_oauth_client_acting_user"
    assert second["down_revision"] == first["revision"]


def test_entrypoint_mirrors_every_new_table_column_and_check():
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in entrypoint, table
    for column in NEW_COLUMNS:
        assert f"ADD COLUMN IF NOT EXISTS {column}" in entrypoint, column
    for check in NEW_CHECKS:
        assert check in entrypoint, check
    assert "ux_client_framework_contracts_client_part" in entrypoint
    assert "ux_client_executive_contracts_client_number" in entrypoint


def test_entrypoint_runs_the_structure_seed_from_the_single_source():
    """Zasiew ma JEDNO źródło SQL — entrypoint importuje je, nie kopiuje."""
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "from app.services.ezdrowie_structure import EZDROWIE_STRUCTURE_SEED_SQL" in (
        entrypoint
    )
    migration = MIGRATION_0312.read_text(encoding="utf-8")
    assert "EZDROWIE_STRUCTURE_SEED_SQL" in migration


def test_health_deep_probes_the_new_table():
    main = MAIN.read_text(encoding="utf-8")
    for table in NEW_TABLES:
        assert f'"{table}"' in main, table


def test_migration_downgrades_drop_what_they_created():
    downgrade = MIGRATION_0312.read_text(encoding="utf-8").split("def downgrade()")[1]
    assert "client_executive_contracts" in downgrade
    assert "executive_contract_id" in downgrade
    assert "project_part" in downgrade
    downgrade = MIGRATION_0313.read_text(encoding="utf-8").split("def downgrade()")[1]
    for column in ("md_optional_total", "status", "note"):
        assert column in downgrade, column


def test_seed_sql_has_no_bind_parameters_and_lists_the_ticket_structure():
    """Migracja przez ``text()`` nie może zawierać ``:słowo`` (CLAUDE.md)."""
    assert not re.search(r"(?<!:):[a-zA-Z_]+", EZDROWIE_STRUCTURE_SEED_SQL.replace("::", ""))
    parts = [part for part, _name, _numbers in EZDROWIE_STRUCTURE]
    assert parts == ["cz1", "cz2", "cz4", "cz5", "cz6"]
    numbers = [n for _p, _n, numbers in EZDROWIE_STRUCTURE for n in numbers]
    assert numbers == ["CeZ/45/2026", "CeZ/242/2025", "CeZ/2/2026"]


@pytest.mark.asyncio
async def test_seed_is_idempotent_and_noop_without_the_client():
    """Dwa uruchomienia = ta sama struktura; bez klienta nic nie powstaje."""
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        # Klient, którego NIE ma — zasiew musi być no-opem.
        missing_id = -abs(uuid.uuid4().int % 1_000_000) - 1
        await db.execute(text(build_structure_seed_sql(missing_id)))
        count = await db.scalar(
            text(
                "SELECT count(*) FROM client_framework_contracts "
                f"WHERE client_id = {missing_id}"
            )
        )
        assert count == 0

        client = Client(name=f"CeZ seed {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        seed_sql = build_structure_seed_sql(client.id)
        await db.execute(text(seed_sql))
        await db.execute(text(seed_sql))
        frameworks = (
            await db.execute(
                text(
                    "SELECT project_part, name FROM client_framework_contracts "
                    f"WHERE client_id = {client.id} ORDER BY project_part"
                )
            )
        ).all()
        assert [row[0] for row in frameworks] == ["cz1", "cz2", "cz4", "cz5", "cz6"]
        executives = (
            await db.execute(
                text(
                    "SELECT ec.number, fc.project_part, ec.status "
                    "FROM client_executive_contracts ec "
                    "JOIN client_framework_contracts fc ON fc.id = ec.framework_contract_id "
                    f"WHERE ec.client_id = {client.id} ORDER BY ec.number"
                )
            )
        ).all()
        assert [(row[0], row[1], row[2]) for row in executives] == [
            ("CeZ/2/2026", "cz2", "active"),
            ("CeZ/242/2025", "cz2", "active"),
            ("CeZ/45/2026", "cz1", "active"),
        ]
        await db.rollback()


@pytest.mark.asyncio
async def test_seed_does_not_resurrect_an_executive_number_corrected_in_the_ui():
    """R8-N6-2: numer poprawiony przez DL nie wraca po deployu jako druga umowa."""
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=f"CeZ rename {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        seed_sql = build_structure_seed_sql(client.id)
        await db.execute(text(seed_sql))
        await db.execute(
            text(
                "UPDATE client_executive_contracts SET number = 'CeZ/002/2026' "
                f"WHERE client_id = {client.id} AND number = 'CeZ/2/2026'"
            )
        )
        await db.execute(text(seed_sql))
        numbers = (
            (
                await db.execute(
                    text(
                        "SELECT number FROM client_executive_contracts "
                        f"WHERE client_id = {client.id} ORDER BY number"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert numbers == ["CeZ/002/2026", "CeZ/242/2025", "CeZ/45/2026"]
        await db.rollback()
