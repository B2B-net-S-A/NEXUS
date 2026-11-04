"""Połączenie ról sourcer + recruiter + tac w `recruiter` (0411) — blok SQL.

Każdy test biegnie w transakcji wycofanej na końcu i asertuje WYŁĄCZNIE po
własnych wierszach: baza testowa jest wspólna, a instrukcje dotykają każdego
konta ze starą rolą.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.stage_notification import (
    ClientStageNotificationOverride,
    RecipientType,
)
from app.models.user import User, UserRole
from app.services import role_merge


def test_retired_roles_normalize_to_recruiter():
    assert role_merge.normalize_role_value("sourcer") == "recruiter"
    assert role_merge.normalize_role_value("tac") == "recruiter"
    assert role_merge.normalize_role_value("recruiter") == "recruiter"
    assert role_merge.normalize_role_value("delivery_lead") == "delivery_lead"


async def _account(
    db: AsyncSession, role: str, roles: list[str], *, completed: bool = True
) -> int:
    """Konto w stanie sprzed migracji — stara rola wpisana surowym SQL-em."""

    user = User(
        email=f"role-merge-{uuid.uuid4().hex[:12]}@example.com",
        name="Role Merge",
        role=UserRole.recruiter,
    )
    db.add(user)
    await db.flush()
    await db.execute(
        text(
            "UPDATE users SET role = CAST(:role AS userrole), "
            "roles = CAST(:roles AS jsonb), profile_completed = :completed "
            "WHERE id = :id"
        ),
        {
            "role": role,
            "roles": json.dumps(roles),
            "completed": completed,
            "id": user.id,
        },
    )
    return user.id


async def _state(db: AsyncSession, user_id: int) -> tuple[str, list[str], bool, int]:
    row = (
        await db.execute(
            text(
                "SELECT role::text, roles, profile_completed, authorization_version "
                "FROM users WHERE id = :id"
            ),
            {"id": user_id},
        )
    ).one()
    return row[0], list(row[1]), row[2], row[3]


async def _run(db: AsyncSession, statements: tuple[str, ...]) -> None:
    for statement in statements:
        await db.execute(text(statement))


@pytest.mark.asyncio
async def test_accounts_become_recruiters_and_second_run_changes_nothing():
    async with AsyncSessionLocal() as db:
        sourcer = await _account(db, "sourcer", ["sourcer"], completed=False)
        tac = await _account(db, "tac", ["tac", "recruiter"])
        orphan = await _account(db, "sourcer", [])
        lead = await _account(
            db, "delivery_lead", ["delivery_lead", "tac"], completed=False
        )
        tcm = await _account(
            db,
            "talent_community_manager",
            ["talent_community_manager", "tac", "recruiter"],
        )
        untouched = await _account(db, "recruiter", ["recruiter"], completed=False)
        before = {
            uid: (await _state(db, uid))[3]
            for uid in (sourcer, tac, orphan, lead, tcm, untouched)
        }

        await _run(db, role_merge.ROLE_MERGE_STATEMENTS)
        first = {uid: await _state(db, uid) for uid in before}
        audited = (
            await db.execute(
                text(
                    "SELECT user_id, original_state FROM role_session_migration_audit "
                    "WHERE migration_key = :key AND user_id = ANY(:ids)"
                ),
                {"key": role_merge.ROLE_MERGE_KEY, "ids": list(before)},
            )
        ).all()

        await _run(db, role_merge.ROLE_MERGE_STATEMENTS)
        second = {uid: await _state(db, uid) for uid in before}
        await db.rollback()

    # Rola główna i dodatkowa przechodzą na rekrutera, bez duplikatu.
    assert first[sourcer][:2] == ("recruiter", ["recruiter"])
    assert first[tac][:2] == ("recruiter", ["recruiter"])
    assert first[orphan][:2] == ("recruiter", ["recruiter"])
    assert first[lead][:2] == ("delivery_lead", ["delivery_lead", "recruiter"])
    assert first[tcm][:2] == (
        "talent_community_manager",
        ["talent_community_manager", "recruiter"],
    )
    # Były sourcer nie przechodzi onboardingu rekrutera; Delivery Lead, który
    # własnego nie skończył, nadal ma go przed sobą.
    assert first[sourcer][2] is True
    assert first[lead][2] is False
    # Sesje unieważnione tylko zmienionym kontom.
    for uid in (sourcer, tac, orphan, lead, tcm):
        assert first[uid][3] == before[uid] + 1
    assert first[untouched] == ("recruiter", ["recruiter"], False, before[untouched])

    original = {row.user_id: row.original_state for row in audited}
    assert set(original) == {sourcer, tac, orphan, lead, tcm}
    assert original[lead]["role"] == "delivery_lead"
    assert original[lead]["roles"] == ["delivery_lead", "tac"]

    # Zbieżność: drugi przebieg nie rusza niczego, także wersji sesji.
    assert second == first


@pytest.mark.asyncio
async def test_restore_brings_back_only_accounts_nobody_changed_since():
    async with AsyncSessionLocal() as db:
        restored = await _account(db, "tac", ["tac"])
        hybrid = await _account(db, "delivery_lead", ["delivery_lead", "sourcer"])
        changed_later = await _account(db, "sourcer", ["sourcer"])
        lost_secondary = await _account(
            db, "recruiter", ["recruiter", "delivery_lead", "tac"]
        )
        await _run(db, role_merge.ROLE_MERGE_STATEMENTS)
        # Admin odebrał po migracji rolę dodatkową — przywrócenie jej nie oddaje.
        await db.execute(
            text("UPDATE users SET roles = '[\"recruiter\"]'::jsonb WHERE id = :id"),
            {"id": lost_secondary},
        )
        await db.execute(
            text(
                "UPDATE users SET role = 'delivery_lead', "
                "roles = '[\"delivery_lead\"]'::jsonb WHERE id = :id"
            ),
            {"id": changed_later},
        )

        await _run(db, role_merge.ROLE_MERGE_RESTORE_STATEMENTS[:1])
        states = {
            uid: await _state(db, uid)
            for uid in (restored, hybrid, changed_later, lost_secondary)
        }
        await db.rollback()

    assert states[restored][:2] == ("tac", ["tac"])
    assert states[hybrid][:2] == ("delivery_lead", ["delivery_lead", "sourcer"])
    assert states[changed_later][:2] == ("delivery_lead", ["delivery_lead"])
    assert states[lost_secondary][:2] == ("recruiter", ["recruiter"])


@pytest.mark.asyncio
async def test_rbac_rows_of_retired_roles_are_deleted_and_kept_for_restore():
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM app_settings WHERE key = ANY(:keys)"),
            {
                "keys": [
                    role_merge.ROLE_MERGE_KEY,
                    role_merge.ROLE_MERGE_DETAILS_KEY,
                ]
            },
        )
        await db.execute(
            text(
                "INSERT INTO rbac_role_section_permissions (role, section, access) "
                "VALUES ('tac', 'sourcing', 'write'), ('sourcer', 'pipeline', 'write') "
                "ON CONFLICT (role, section) DO NOTHING"
            )
        )
        await db.execute(
            text(
                "INSERT INTO rbac_role_action_permissions (role, action, access) "
                "VALUES ('tac', 'b2b_contract_generator', 'manage') "
                "ON CONFLICT (role, action) DO NOTHING"
            )
        )
        recruiter_rows = await db.scalar(
            text(
                "SELECT count(*) FROM rbac_role_section_permissions "
                "WHERE role = 'recruiter'"
            )
        )

        await _run(db, role_merge.ROLE_MERGE_STATEMENTS)
        left = await db.scalar(
            text(
                "SELECT (SELECT count(*) FROM rbac_role_section_permissions "
                "        WHERE role IN ('sourcer', 'tac')) "
                "     + (SELECT count(*) FROM rbac_role_action_permissions "
                "        WHERE role IN ('sourcer', 'tac'))"
            )
        )
        recruiter_rows_after = await db.scalar(
            text(
                "SELECT count(*) FROM rbac_role_section_permissions "
                "WHERE role = 'recruiter'"
            )
        )
        receipt = await db.scalar(
            text("SELECT value FROM app_settings WHERE key = :key"),
            {"key": role_merge.ROLE_MERGE_KEY},
        )
        details = await db.scalar(
            text("SELECT value FROM app_settings WHERE key = :key"),
            {"key": role_merge.ROLE_MERGE_DETAILS_KEY},
        )

        await _run(db, role_merge.ROLE_MERGE_RESTORE_STATEMENTS[1:3])
        back = await db.scalar(
            text(
                "SELECT count(*) FROM rbac_role_section_permissions "
                "WHERE role IN ('sourcer', 'tac')"
            )
        )
        await db.rollback()

    assert left == 0
    assert recruiter_rows_after == recruiter_rows
    # Paragon niesie same liczniki; wiersze do przywrócenia leżą pod osobnym kluczem.
    assert receipt["rbac_section_rows_deleted"] >= 2
    assert receipt["rbac_action_rows_deleted"] >= 1
    assert {row["role"] for row in details["sections"]} == {"sourcer", "tac"}
    assert back == receipt["rbac_section_rows_deleted"]


@pytest.mark.asyncio
async def test_stage_overrides_for_retired_roles_collapse_into_one_recruiter_rule():
    async with AsyncSessionLocal() as db:
        stage_ids = (
            (
                await db.execute(
                    text("SELECT id FROM pipeline_stage_defs ORDER BY id LIMIT 2")
                )
            )
            .scalars()
            .all()
        )
        if len(stage_ids) < 2:
            await db.rollback()
            pytest.skip("baza testowa nie ma dwóch definicji etapów")
        client = Client(name=f"Role Merge {uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        with_recruiter, without_recruiter = stage_ids
        for stage_id, role in (
            (with_recruiter, "tac"),
            (with_recruiter, "recruiter"),
            (with_recruiter, "sourcer"),
            (without_recruiter, "sourcer"),
            (without_recruiter, "tac"),
        ):
            db.add(
                ClientStageNotificationOverride(
                    client_id=client.id,
                    stage_def_id=stage_id,
                    recipient_type=RecipientType.role,
                    role=role,
                )
            )
        await db.flush()

        await _run(db, role_merge.ROLE_MERGE_STATEMENTS)
        rows = (
            await db.execute(
                text(
                    "SELECT stage_def_id, role FROM client_stage_notification_overrides "
                    "WHERE client_id = :client ORDER BY stage_def_id"
                ),
                {"client": client.id},
            )
        ).all()
        await db.rollback()

    assert [(row.stage_def_id, row.role) for row in rows] == [
        (with_recruiter, "recruiter"),
        (without_recruiter, "recruiter"),
    ]
