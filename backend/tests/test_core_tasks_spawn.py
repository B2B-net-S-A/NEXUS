"""`app.core.tasks.spawn` — zadanie w tle z trzymaną referencją (audyt 25.09.2026).

Goły `asyncio.create_task(...)` bez referencji może zniknąć pod GC w połowie
biegu, a jego wyjątek nie zostawia śladu. Endpointy startujące biegi w tle
(sync Traffita, backfille, import, Autenti) używają teraz `spawn`.
"""

from __future__ import annotations

import ast
import asyncio
import logging
from pathlib import Path

import pytest

from app.core import tasks as core_tasks

_BACKEND = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_spawn_holds_reference_until_done_and_logs_failure(caplog) -> None:
    gate = asyncio.Event()

    async def _boom() -> None:
        await gate.wait()
        raise RuntimeError("kaboom")

    with caplog.at_level(logging.ERROR, logger="app.core.tasks"):
        task = core_tasks.spawn(_boom(), "test_boom")
        assert task in core_tasks._bg_tasks  # noqa: SLF001
        gate.set()
        with pytest.raises(RuntimeError):
            await task
        await asyncio.sleep(0)

    assert task not in core_tasks._bg_tasks  # noqa: SLF001
    assert any("test_boom" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    "module",
    [
        "app/api/admin_traffit.py",
        "app/api/admin_candidates.py",
        "app/api/admin_import.py",
        "app/api/autenti.py",
        "app/api/microsoft365.py",
    ],
)
def test_background_endpoints_do_not_use_bare_create_task(module: str) -> None:
    tree = ast.parse((_BACKEND / module).read_text(encoding="utf-8"))
    bare = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_task"
    ]
    assert bare == [], f"{module}: goły create_task w liniach {bare} — użyj spawn()"
