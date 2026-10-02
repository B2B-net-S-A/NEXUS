"""0408 na prawdziwym Postgresie: CHECK, zasiew i siatka przy starcie.

Każdy test, który coś zmienia, robi to w transakcji wycofywanej na końcu —
macierz uprawnień wspólnej bazy testowej zostaje nietknięta.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import settings
from app.models.user import User, UserRole
from app.services import named_permissions_bootstrap as named
from app.services import permission_catalog as catalog
from app.services import permission_schema as schema
from app.services import signature_policy_bootstrap as signature
from app.services.startup_locks import is_lock_timeout

_KEYS = ", ".join(f"'{key}'" for key in catalog.SEEDED_KEYS)
_NARROW_CHECK = "action IN ('b2b_contract_generator', 'b2b_signature_confirmation')"
_TAC_SIGNATURE = (
    "SELECT access FROM rbac_role_action_permissions "
    "WHERE role = 'tac' AND action = 'b2b_signature_confirmation'"
)


@pytest.fixture
async def engine():
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _stored_sections(connection) -> dict[str, dict[str, str]]:
    rows = await connection.execute(
        text("SELECT role, section, access FROM rbac_role_section_permissions")
    )
    sections: dict[str, dict[str, str]] = {}
    for role, section, access in rows.all():
        sections.setdefault(role, {})[section] = access
    return sections


async def _seeded_rows(connection) -> dict[tuple[str, str], str]:
    rows = await connection.execute(
        text(
            "SELECT role, action, access FROM rbac_role_action_permissions "
            f"WHERE action IN ({_KEYS})"
        )
    )
    return {(role, action): access for role, action, access in rows.all()}


async def _revision(connection) -> int:
    return await connection.scalar(
        text("SELECT revision FROM rbac_policy_state WHERE id = 1")
    )


async def test_migrated_database_has_the_wide_check_and_every_row(engine) -> None:
    async with engine.connect() as connection:
        assert await connection.scalar(text(schema.READY_SQL)) is True


@pytest.mark.parametrize(
    "changed_sections",
    [
        {},
        {("delivery_lead", "delivery"): "read"},
        {("delivery_lead", "delivery"): "none"},
        {("delivery_lead", "pipeline"): "read"},
        {("finance", "finance"): "none"},
        {("finance", "finance"): "read"},
        {("finance", "delivery"): "read"},
        {("talent_community_manager", "delivery"): "read"},
        {("talent_community_manager", "delivery"): "none"},
    ],
)
async def test_seed_sql_is_the_python_seed_rule(engine, changed_sections) -> None:
    """Zasiew w SQL-u i ``seed_rows_for_role`` to ta sama reguła.

    Resolver używa funkcji w Pythonie dla roli bez wierszy, migracja — SQL-a.
    Rozjazd dałby inne uprawnienia zależnie od tego, która ścieżka zadziałała.
    """

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            for (role, section), access in changed_sections.items():
                await connection.execute(
                    text(
                        "UPDATE rbac_role_section_permissions SET access = :access "
                        "WHERE role = :role AND section = :section"
                    ),
                    {"access": access, "role": role, "section": section},
                )
            await connection.execute(
                text(f"DELETE FROM rbac_role_action_permissions WHERE action IN ({_KEYS})")
            )
            await connection.execute(text(schema.SEED_SQL))

            sections = await _stored_sections(connection)
            seeded = await _seeded_rows(connection)
            for role in catalog.ROLES:
                expected = catalog.seed_rows_for_role(role, sections.get(role, {}))
                assert {
                    key: seeded[(role, key)] for key in catalog.SEEDED_KEYS
                } == expected, role
        finally:
            await transaction.rollback()


async def test_seed_leaves_a_row_set_in_the_panel(engine) -> None:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                text(
                    "UPDATE rbac_role_action_permissions SET access = 'none' "
                    "WHERE role = 'delivery_lead' AND action = 'clients_edit'"
                )
            )
            await connection.execute(text(schema.SEED_SQL))
            assert (await _seeded_rows(connection))[
                ("delivery_lead", "clients_edit")
            ] == "none"
        finally:
            await transaction.rollback()


async def test_bootstrap_on_a_migrated_database_changes_nothing(engine, capsys) -> None:
    async with engine.connect() as connection:
        before = await _revision(connection)

    await named.main(engine)

    assert "Named permissions verified" in capsys.readouterr().out
    async with engine.connect() as connection:
        assert await _revision(connection) == before


async def test_bootstrap_repairs_a_database_that_missed_the_migration(engine) -> None:
    """Bookmark Alembica bez 0408: wąski CHECK i brak wierszy."""

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            for table in schema.ACTION_TABLES:
                name = schema.constraint_name(table)
                await connection.execute(
                    text(f"DELETE FROM {table} WHERE action IN ({_KEYS})")
                )
                await connection.execute(
                    text(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
                )
                await connection.execute(
                    text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({_NARROW_CHECK})")
                )
            assert await connection.scalar(text(schema.READY_SQL)) is False
            before = await _revision(connection)

            await named.ensure_named_permissions(connection)

            assert await connection.scalar(text(schema.READY_SQL)) is True
            assert await _revision(connection) == before + 1
            sections = await _stored_sections(connection)
            seeded = await _seeded_rows(connection)
            assert seeded[("finance", "contracts_orders_edit")] == (
                catalog.seed_rows_for_role("finance", sections.get("finance", {}))[
                    "contracts_orders_edit"
                ]
            )
        finally:
            await transaction.rollback()


async def test_rerunning_the_signature_migration_keeps_the_wide_check(engine) -> None:
    """Naprawa 0282 przy starcie nie może zwęzić CHECK-a po 0408."""

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.run_sync(signature.ensure_signature_policy)
            assert await connection.scalar(text(schema.READY_SQL)) is True
        finally:
            await transaction.rollback()


async def test_tac_signature_goes_off_only_when_nobody_set_it(engine) -> None:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(
                text(
                    "UPDATE rbac_role_action_permissions "
                    "SET access = 'manage', updated_by = NULL "
                    "WHERE role = 'tac' AND action = 'b2b_signature_confirmation'"
                )
            )
            await connection.execute(text(schema.TAC_SIGNATURE_SQL))
            assert await connection.scalar(text(_TAC_SIGNATURE)) == "none"

            session = AsyncSession(bind=connection, expire_on_commit=False)
            admin = User(
                email=f"pytest-named-permissions-{uuid.uuid4().hex[:10]}@example.com",
                name="Named Permissions Admin",
                role=UserRole.admin,
                roles=[UserRole.admin.value],
                is_active=True,
                email_verified=True,
                profile_completed=True,
            )
            session.add(admin)
            await session.flush()
            await connection.execute(
                text(
                    "UPDATE rbac_role_action_permissions "
                    "SET access = 'manage', updated_by = :admin "
                    "WHERE role = 'tac' AND action = 'b2b_signature_confirmation'"
                ),
                {"admin": admin.id},
            )
            await connection.execute(text(schema.TAC_SIGNATURE_SQL))
            assert await connection.scalar(text(_TAC_SIGNATURE)) == "manage"
            await session.close()
        finally:
            await transaction.rollback()


async def test_bootstrap_behind_a_dump_is_a_soft_skip(engine, monkeypatch, capsys) -> None:
    monkeypatch.setattr(named, "BOOT_LOCK_TIMEOUT", "200ms")
    monkeypatch.setattr(named, "READY_SQL", "SELECT false")

    async with engine.connect() as holder:
        transaction = await holder.begin()
        try:
            await holder.execute(
                text("LOCK TABLE rbac_role_action_permissions IN ACCESS SHARE MODE")
            )
            await named.main(engine)
        finally:
            await transaction.rollback()

    out = capsys.readouterr().out
    assert "skipped after a lock timeout" in out
    assert "verified" not in out
    async with engine.connect() as connection:
        assert await connection.scalar(text(schema.READY_SQL)) is True


async def test_bootstrap_other_errors_still_fail_the_boot(engine, monkeypatch) -> None:
    monkeypatch.setattr(
        named, "READY_SQL", "SELECT no_such_column FROM rbac_policy_state"
    )

    with pytest.raises(DBAPIError) as error:
        await named.main(engine)
    assert not is_lock_timeout(error.value)
