"""Focused tests for transactional Finance role relationship cleanup."""

from __future__ import annotations

from collections.abc import Iterable
from unittest.mock import AsyncMock, call

import pytest

from app.services.finance_role_cleanup import clear_recruitment_access_for_finance


_MUTATION_KEYS = (
    "delivery_lead_client_assignments",
    "client_tac_assignments",
    "tac_delivery_lead_assignments",
    "tac_linkedin_farming",
    "user_competence_categories",
    "job_collaborators",
    "jobs_recruiter_owner",
    "jobs_delivery_lead_owner",
    "jobs_tac_owner",
    "contact_relationship_owner",
    "saved_search_alerts_disabled",
    "recruitment_notifications",
)


class _Result:
    def __init__(self, *, values: Iterable[int] = (), rowcount: int = 0) -> None:
        self._values = list(values)
        self.rowcount = rowcount

    def scalars(self) -> _Result:
        return self

    def all(self) -> list[int]:
        return self._values


class _ScriptedDatabase:
    """Minimal AsyncSession double that preserves cleanup call boundaries."""

    def __init__(
        self,
        *,
        client_id_batches: Iterable[Iterable[int]],
        mutation_rowcount_batches: Iterable[Iterable[int]],
    ) -> None:
        self._client_id_batches = [list(values) for values in client_id_batches]
        self._mutation_rowcount_batches = [
            list(values) for values in mutation_rowcount_batches
        ]
        self._current_mutation_rowcounts: list[int] = []
        self.statements: list[object] = []
        self.scalar_calls: list[tuple[object, object | None]] = []

    async def execute(
        self, statement: object, parameters: object | None = None
    ) -> _Result:
        self.statements.append(statement)
        if bool(getattr(statement, "is_select", False)):
            assert not self._current_mutation_rowcounts
            self._current_mutation_rowcounts = self._mutation_rowcount_batches.pop(0)
            return _Result(values=self._client_id_batches.pop(0))

        assert self._current_mutation_rowcounts, "unexpected cleanup mutation"
        return _Result(rowcount=self._current_mutation_rowcounts.pop(0))

    async def scalar(self, statement: object, parameters: object | None = None) -> None:
        self.scalar_calls.append((statement, parameters))
        return None

    def assert_script_consumed(self) -> None:
        assert self._client_id_batches == []
        assert self._mutation_rowcount_batches == []
        assert self._current_mutation_rowcounts == []


@pytest.mark.asyncio
async def test_cleanup_invalidates_every_dl_scope_for_distinct_tac_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _ScriptedDatabase(
        client_id_batches=[[31, 12, 19]],
        mutation_rowcount_batches=[range(1, len(_MUTATION_KEYS) + 1)],
    )
    invalidator = AsyncMock(side_effect=[2, 1, 3])
    monkeypatch.setattr(
        "app.services.finance_role_cleanup.invalidate_delivery_lead_scope_for_client",
        invalidator,
    )

    counts = await clear_recruitment_access_for_finance(
        db,  # type: ignore[arg-type]
        user_id=77,
    )

    invalidator.assert_has_awaits([call(db, 12), call(db, 19), call(db, 31)])
    assert invalidator.await_count == 3
    assert counts["delivery_lead_sessions_invalidated"] == 6
    assert {key: counts[key] for key in _MUTATION_KEYS} == dict(
        zip(_MUTATION_KEYS, range(1, len(_MUTATION_KEYS) + 1), strict=True)
    )
    assert counts["dr_tac_delivery_lead_assignments"] == 0
    assert counts["dr_sourcer_category_assignments"] == 0
    db.assert_script_consumed()


@pytest.mark.asyncio
async def test_cleanup_is_idempotent_on_second_invocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _ScriptedDatabase(
        client_id_batches=[[51, 52], []],
        mutation_rowcount_batches=[
            [1] * len(_MUTATION_KEYS),
            [0] * len(_MUTATION_KEYS),
        ],
    )
    invalidator = AsyncMock(side_effect=[2, 1])
    monkeypatch.setattr(
        "app.services.finance_role_cleanup.invalidate_delivery_lead_scope_for_client",
        invalidator,
    )

    first_counts = await clear_recruitment_access_for_finance(
        db,  # type: ignore[arg-type]
        user_id=77,
    )
    second_counts = await clear_recruitment_access_for_finance(
        db,  # type: ignore[arg-type]
        user_id=77,
    )

    assert first_counts["delivery_lead_sessions_invalidated"] == 3
    assert all(first_counts[key] == 1 for key in _MUTATION_KEYS)
    assert second_counts["delivery_lead_sessions_invalidated"] == 0
    assert all(second_counts[key] == 0 for key in second_counts)
    invalidator.assert_has_awaits([call(db, 51), call(db, 52)])
    assert invalidator.await_count == 2
    db.assert_script_consumed()


@pytest.mark.asyncio
async def test_cleanup_without_tac_assignments_does_not_invalidate_dl_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _ScriptedDatabase(
        client_id_batches=[[]],
        # The account can still have its own DL relationships cleaned up.  That
        # must not revoke sessions of unrelated DLs when it has no TAC clients.
        mutation_rowcount_batches=[[2, *([0] * (len(_MUTATION_KEYS) - 1))]],
    )
    invalidator = AsyncMock()
    monkeypatch.setattr(
        "app.services.finance_role_cleanup.invalidate_delivery_lead_scope_for_client",
        invalidator,
    )

    counts = await clear_recruitment_access_for_finance(
        db,  # type: ignore[arg-type]
        user_id=77,
    )

    invalidator.assert_not_awaited()
    assert counts["delivery_lead_sessions_invalidated"] == 0
    assert counts["delivery_lead_client_assignments"] == 2
    assert all(
        counts[key] == 0
        for key in counts
        if key not in {"delivery_lead_client_assignments"}
    )
    db.assert_script_consumed()
