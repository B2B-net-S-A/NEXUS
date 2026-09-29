"""Priority Work read paths must not write (29.09.2026).

The panel on every recruitment (`GET /api/priority-work/jobs/{id}`) went
through `current_plan`, which called `ensure_priority_state` — an
`INSERT … ON CONFLICT DO NOTHING` — so each view of a recruitment ran a write
in the request transaction.
"""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import priority_work
from app.services import priority_work_service


class _ReadOnlyDb:
    """Fake session: `scalar` answers, `execute` (the upsert) fails the test."""

    def __init__(self, state):
        self._state = state
        self.scalar = AsyncMock(return_value=state)

    async def execute(self, *_args, **_kwargs):  # pragma: no cover - must not run
        raise AssertionError("a read path executed a write statement")


@pytest.mark.asyncio
async def test_current_plan_without_a_state_row_does_not_create_it() -> None:
    db = _ReadOnlyDb(state=None)

    assert await priority_work_service.current_plan(db) is None
    db.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_current_plan_with_a_state_row_without_a_plan_only_reads() -> None:
    db = _ReadOnlyDb(state=SimpleNamespace(current_plan_id=None))

    assert await priority_work_service.current_plan(db) is None


@pytest.mark.asyncio
async def test_status_without_a_state_row_answers_defaults_without_writing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(priority_work, "current_plan", AsyncMock(return_value=None))
    db = _ReadOnlyDb(state=None)

    payload = await priority_work.get_priority_status(SimpleNamespace(id=1), db)

    assert payload["current_plan_id"] is None
    assert payload["metrics"] == {}
    assert payload["worker_heartbeat_at"] is None
    assert payload["plan_overdue"] is False


def _get_handlers() -> list[ast.AsyncFunctionDef]:
    tree = ast.parse(inspect.getsource(priority_work))
    handlers = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "get"
            ):
                handlers.append(node)
    return handlers


def test_no_get_handler_upserts_the_priority_state() -> None:
    handlers = _get_handlers()
    assert handlers, "expected GET handlers in the Priority Work router"
    offenders = [
        handler.name
        for handler in handlers
        if "ensure_priority_state" in ast.unparse(handler)
    ]
    assert offenders == []
