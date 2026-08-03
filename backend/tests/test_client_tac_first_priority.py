"""Focused unit tests for TAC-centric client priority commands."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.api.clients_team import _resolve_first_priority_reconciliation
from app.models.team_structure import ClientTacAssignment
from app.services.auto_assign_owners import resolve_default_owners
from app.services.client_tac_assignments import (
    FirstPrioritySuccessorRequired,
    remove_client_tac_assignment,
    set_first_priority_for_tac,
    toggle_legacy_primary_tac,
    upsert_client_tac_assignment,
)


pytestmark = pytest.mark.asyncio


async def test_reconciliation_json_value_has_an_explicit_postgres_type() -> None:
    """asyncpg cannot infer a bind type inside jsonb_build_object()."""

    db = AsyncMock()

    await _resolve_first_priority_reconciliation(
        db,
        tac_user_id=7,
        selected_client_id=10,
        resolved_by=3,
    )

    statement, parameters = db.execute.await_args.args
    assert "CAST(:selected_client_id AS INTEGER)" in str(statement)
    assert parameters == {
        "tac_user_id": 7,
        "selected_client_id": 10,
        "resolved_by": 3,
    }


class _Database:
    def __init__(self) -> None:
        self.added: list[ClientTacAssignment] = []
        self.deleted: list[ClientTacAssignment] = []
        self.flushes = 0

    def add(self, value: ClientTacAssignment) -> None:
        self.added.append(value)

    async def delete(self, value: ClientTacAssignment) -> None:
        self.deleted.append(value)

    async def flush(self) -> None:
        self.flushes += 1


class _ResolverResult:
    def __init__(self, values) -> None:
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return list(self.values)

    def scalar_one_or_none(self):
        return self.values


class _ResolverDatabase:
    def __init__(self, tac_ids: list[int], dl_id: int | None) -> None:
        self.results = [_ResolverResult(tac_ids), _ResolverResult(dl_id)]

    async def execute(self, _statement):
        return self.results.pop(0)


def _assignment(
    assignment_id: int,
    *,
    client_id: int,
    tac_user_id: int = 7,
    first_priority: bool | None,
    legacy_primary: bool = False,
) -> ClientTacAssignment:
    return ClientTacAssignment(
        id=assignment_id,
        client_id=client_id,
        tac_user_id=tac_user_id,
        is_first_priority_for_tac=first_priority,
        is_primary=legacy_primary,
    )


async def test_first_assignment_auto_prioritises_but_later_one_does_not(
    monkeypatch,
) -> None:
    lock_rows = AsyncMock(side_effect=[[], []])
    monkeypatch.setattr(
        "app.services.client_tac_assignments._lock_relationship_rows",
        lock_rows,
    )
    db = _Database()

    first = await upsert_client_tac_assignment(
        db,  # type: ignore[arg-type]
        client_id=10,
        tac_user_id=7,
        is_primary=False,
        is_first_priority_for_tac=None,
    )
    # Include the first assignment in the second command's locked view.
    lock_rows.side_effect = [[first.assignment]]
    second = await upsert_client_tac_assignment(
        db,  # type: ignore[arg-type]
        client_id=20,
        tac_user_id=7,
        is_primary=False,
        is_first_priority_for_tac=None,
    )

    assert first.assignment.is_first_priority_for_tac is True
    assert second.assignment.is_first_priority_for_tac is False
    assert first.assignment.is_primary is False
    assert second.assignment.is_primary is False


async def test_promoting_priority_demotes_previous_without_touching_legacy(
    monkeypatch,
) -> None:
    old = _assignment(
        1,
        client_id=10,
        first_priority=True,
        legacy_primary=True,
    )
    new = _assignment(
        2,
        client_id=20,
        first_priority=False,
        legacy_primary=False,
    )
    monkeypatch.setattr(
        "app.services.client_tac_assignments._lock_relationship_rows",
        AsyncMock(return_value=[old, new]),
    )
    db = _Database()

    result = await set_first_priority_for_tac(
        db,  # type: ignore[arg-type]
        client_id=20,
        tac_user_id=7,
        enabled=True,
    )

    assert result is new
    assert old.is_first_priority_for_tac is False
    assert new.is_first_priority_for_tac is True
    assert old.is_primary is True
    assert new.is_primary is False
    assert db.flushes == 2


async def test_disabling_current_priority_requires_successor(monkeypatch) -> None:
    current = _assignment(1, client_id=10, first_priority=True)
    alternative = _assignment(2, client_id=20, first_priority=False)
    monkeypatch.setattr(
        "app.services.client_tac_assignments._lock_relationship_rows",
        AsyncMock(return_value=[current, alternative]),
    )

    with pytest.raises(FirstPrioritySuccessorRequired):
        await set_first_priority_for_tac(
            _Database(),  # type: ignore[arg-type]
            client_id=10,
            tac_user_id=7,
            enabled=False,
        )

    assert current.is_first_priority_for_tac is True
    assert alternative.is_first_priority_for_tac is False


async def test_disabling_current_priority_hands_over_atomically(monkeypatch) -> None:
    current = _assignment(1, client_id=10, first_priority=True)
    successor = _assignment(2, client_id=20, first_priority=None)
    monkeypatch.setattr(
        "app.services.client_tac_assignments._lock_relationship_rows",
        AsyncMock(return_value=[current, successor]),
    )
    db = _Database()

    await set_first_priority_for_tac(
        db,  # type: ignore[arg-type]
        client_id=10,
        tac_user_id=7,
        enabled=False,
        successor_client_id=20,
    )

    assert current.is_first_priority_for_tac is False
    assert successor.is_first_priority_for_tac is True
    assert db.flushes == 2


async def test_delete_current_priority_requires_and_applies_successor(
    monkeypatch,
) -> None:
    current = _assignment(1, client_id=10, first_priority=True)
    successor = _assignment(2, client_id=20, first_priority=False)
    lock_rows = AsyncMock(return_value=[current, successor])
    monkeypatch.setattr(
        "app.services.client_tac_assignments._lock_relationship_rows",
        lock_rows,
    )

    with pytest.raises(FirstPrioritySuccessorRequired):
        await remove_client_tac_assignment(
            _Database(),  # type: ignore[arg-type]
            client_id=10,
            tac_user_id=7,
        )

    db = _Database()
    await remove_client_tac_assignment(
        db,  # type: ignore[arg-type]
        client_id=10,
        tac_user_id=7,
        successor_client_id=20,
    )

    assert successor.is_first_priority_for_tac is True
    assert db.deleted == [current]
    assert db.flushes == 3


async def test_legacy_toggle_never_rewrites_first_priority(monkeypatch) -> None:
    target = _assignment(
        1,
        client_id=10,
        first_priority=True,
        legacy_primary=False,
    )
    monkeypatch.setattr(
        "app.services.client_tac_assignments._lock_relationship_rows",
        AsyncMock(return_value=[target]),
    )

    await toggle_legacy_primary_tac(
        _Database(),  # type: ignore[arg-type]
        client_id=10,
        tac_user_id=7,
    )

    assert target.is_primary is True
    assert target.is_first_priority_for_tac is True


async def test_new_priority_only_post_preserves_legacy_primary(monkeypatch) -> None:
    target = _assignment(
        1,
        client_id=10,
        first_priority=None,
        legacy_primary=True,
    )
    monkeypatch.setattr(
        "app.services.client_tac_assignments._lock_relationship_rows",
        AsyncMock(return_value=[target]),
    )

    result = await upsert_client_tac_assignment(
        _Database(),  # type: ignore[arg-type]
        client_id=10,
        tac_user_id=7,
        is_primary=None,
        is_first_priority_for_tac=True,
    )

    assert result.assignment.is_primary is True
    assert result.assignment.is_first_priority_for_tac is True
    assert result.legacy_primary_changed is False


async def test_job_owner_resolver_uses_only_a_sole_active_tac() -> None:
    one = await resolve_default_owners(
        _ResolverDatabase([7], 9),  # type: ignore[arg-type]
        10,
    )
    many = await resolve_default_owners(
        _ResolverDatabase([7, 8], 9),  # type: ignore[arg-type]
        10,
    )

    assert one.tac_id == 7
    assert one.delivery_lead_id == 9
    assert many.tac_id is None
    assert many.delivery_lead_id == 9
