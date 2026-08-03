"""Focused tests for session invalidation after relationship-scope changes."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.api.clients_team import (
    assign_tac_to_client,
    remove_tac_from_client,
    toggle_tac_primary,
)
from app.api.team_structure import (
    assign_dl_to_client,
    remove_dl_client,
    toggle_dl_client_head,
)
from app.models.client import Client
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User, UserRole
from app.schemas.client_team import ClientTacAssignmentCreate
from app.schemas.team_structure import AssignDlClientPayload
from app.services.authorization_invalidation import (
    invalidate_delivery_lead_scope_for_client,
    invalidate_delivery_lead_scope_for_users,
)


class _ScalarResult:
    def __init__(self, value=None, *, rowcount: int = 0):
        self.value = value
        self.rowcount = rowcount

    def scalar_one_or_none(self):
        return self.value


class _Database:
    def __init__(self, *results):
        self.results = list(results)
        self.statements = []
        self.added = []
        self.deleted = []
        self.commits = 0
        self.flushes = 0

    async def execute(self, statement):
        self.statements.append(statement)
        return self.results.pop(0) if self.results else _ScalarResult(rowcount=0)

    def add(self, value):
        self.added.append(value)

    async def delete(self, value):
        self.deleted.append(value)

    async def commit(self):
        self.commits += 1

    async def flush(self):
        self.flushes += 1


def _user(user_id: int, role: UserRole) -> User:
    return User(
        id=user_id,
        email=f"{user_id}@example.com",
        name=f"User {user_id}",
        role=role,
        roles=[role.value],
        is_active=True,
        profile_completed=True,
        authorization_version=1,
    )


@pytest.mark.asyncio
async def test_user_scope_invalidation_is_atomic_active_dl_only() -> None:
    db = _Database(_ScalarResult(rowcount=2))

    changed = await invalidate_delivery_lead_scope_for_users(
        db,  # type: ignore[arg-type]
        [12, 12, 15],
    )

    assert changed == 2
    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert sql.startswith("UPDATE users SET ")
    assert "authorization_version=(users.authorization_version +" in sql
    assert "tokens_valid_after=now()" in sql
    assert "users.is_active IS true" in sql
    assert "users.role =" in sql
    assert "users.roles @>" in sql


@pytest.mark.asyncio
async def test_client_scope_invalidation_targets_assigned_active_dls() -> None:
    db = _Database(_ScalarResult(rowcount=3))

    changed = await invalidate_delivery_lead_scope_for_client(
        db,  # type: ignore[arg-type]
        44,
    )

    assert changed == 3
    sql = str(db.statements[0].compile(dialect=postgresql.dialect()))
    assert "delivery_lead_client_assignments.delivery_lead_user_id" in sql
    assert "delivery_lead_client_assignments.client_id =" in sql
    assert "users.is_active IS true" in sql
    assert "authorization_version=(users.authorization_version +" in sql


@pytest.mark.asyncio
async def test_dl_client_upsert_does_not_revoke_session_on_noop(monkeypatch) -> None:
    dl = _user(12, UserRole.delivery_lead)
    existing = DeliveryLeadClientAssignment(
        id=90,
        delivery_lead_user_id=12,
        client_id=44,
        is_head=False,
    )
    db = _Database(_ScalarResult(dl), _ScalarResult(existing))
    invalidator = AsyncMock()
    monkeypatch.setattr(
        "app.api.team_structure.invalidate_delivery_lead_scope_for_users",
        invalidator,
    )

    result = await assign_dl_to_client(
        AssignDlClientPayload(
            delivery_lead_user_id=12,
            client_id=44,
            is_head=False,
        ),
        _user(1, UserRole.admin),
        db,  # type: ignore[arg-type]
    )

    assert result == {"ok": True}
    invalidator.assert_not_awaited()
    assert db.commits == 1


@pytest.mark.asyncio
async def test_dl_client_upsert_revokes_every_changed_dl(monkeypatch) -> None:
    dl = _user(12, UserRole.delivery_lead)
    previous_head = DeliveryLeadClientAssignment(
        id=89,
        delivery_lead_user_id=15,
        client_id=44,
        is_head=True,
    )
    existing = DeliveryLeadClientAssignment(
        id=90,
        delivery_lead_user_id=12,
        client_id=44,
        is_head=False,
    )
    db = _Database(
        _ScalarResult(dl),
        _ScalarResult(previous_head),
        _ScalarResult(existing),
    )
    invalidator = AsyncMock()
    monkeypatch.setattr(
        "app.api.team_structure.invalidate_delivery_lead_scope_for_users",
        invalidator,
    )

    await assign_dl_to_client(
        AssignDlClientPayload(
            delivery_lead_user_id=12,
            client_id=44,
            is_head=True,
        ),
        _user(1, UserRole.admin),
        db,  # type: ignore[arg-type]
    )

    assert previous_head.is_head is False
    assert existing.is_head is True
    invalidator.assert_awaited_once_with(db, {12, 15})


@pytest.mark.asyncio
async def test_dl_client_toggle_and_delete_revoke_changed_dl(monkeypatch) -> None:
    invalidator = AsyncMock()
    monkeypatch.setattr(
        "app.api.team_structure.invalidate_delivery_lead_scope_for_users",
        invalidator,
    )

    assignment = DeliveryLeadClientAssignment(
        id=90,
        delivery_lead_user_id=12,
        client_id=44,
        is_head=True,
    )
    toggle_db = _Database(_ScalarResult(assignment))
    await toggle_dl_client_head(
        90,
        _user(1, UserRole.admin),
        toggle_db,  # type: ignore[arg-type]
    )
    assert assignment.is_head is False
    invalidator.assert_awaited_once_with(toggle_db, {12})

    invalidator.reset_mock()
    delete_db = _Database(_ScalarResult(assignment))
    await remove_dl_client(
        90,
        _user(1, UserRole.admin),
        delete_db,  # type: ignore[arg-type]
    )
    assert delete_db.deleted == [assignment]
    invalidator.assert_awaited_once_with(delete_db, {12})


@pytest.mark.asyncio
async def test_tac_client_upsert_revokes_client_dls_only_on_change(
    monkeypatch,
) -> None:
    ensure_client = AsyncMock(return_value=Client(id=44, name="Client"))
    load_tac = AsyncMock(return_value=_user(22, UserRole.tac))
    invalidator = AsyncMock()
    monkeypatch.setattr("app.api.clients_team._ensure_client_exists", ensure_client)
    monkeypatch.setattr("app.api.clients_team._load_user_for_tac", load_tac)
    monkeypatch.setattr(
        "app.api.clients_team.invalidate_delivery_lead_scope_for_client",
        invalidator,
    )

    existing = ClientTacAssignment(
        id=70,
        client_id=44,
        tac_user_id=22,
        is_primary=False,
    )
    no_op_db = _Database(_ScalarResult(existing))
    await assign_tac_to_client(
        44,
        ClientTacAssignmentCreate(user_id=22, is_primary=False),
        _user(1, UserRole.admin),
        no_op_db,  # type: ignore[arg-type]
    )
    invalidator.assert_not_awaited()

    changed_db = _Database(_ScalarResult(None), _ScalarResult(existing))
    await assign_tac_to_client(
        44,
        ClientTacAssignmentCreate(user_id=22, is_primary=True),
        _user(1, UserRole.admin),
        changed_db,  # type: ignore[arg-type]
    )
    assert existing.is_primary is True
    invalidator.assert_awaited_once_with(changed_db, 44)


@pytest.mark.asyncio
async def test_tac_client_toggle_and_delete_revoke_client_dls(monkeypatch) -> None:
    invalidator = AsyncMock()
    monkeypatch.setattr(
        "app.api.clients_team.invalidate_delivery_lead_scope_for_client",
        invalidator,
    )
    assignment = ClientTacAssignment(
        id=70,
        client_id=44,
        tac_user_id=22,
        is_primary=True,
    )

    toggle_db = _Database(_ScalarResult(assignment))
    await toggle_tac_primary(
        44,
        22,
        _user(1, UserRole.admin),
        toggle_db,  # type: ignore[arg-type]
    )
    assert assignment.is_primary is False
    invalidator.assert_awaited_once_with(toggle_db, 44)

    invalidator.reset_mock()
    delete_db = _Database(_ScalarResult(assignment))
    await remove_tac_from_client(
        44,
        22,
        _user(1, UserRole.admin),
        delete_db,  # type: ignore[arg-type]
    )
    assert delete_db.deleted == [assignment]
    invalidator.assert_awaited_once_with(delete_db, 44)
