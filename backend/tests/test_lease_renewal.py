"""Runda 7 (R7-N6-2): przejściowy błąd bazy przy odnowieniu dzierżawy nie
kończy opłaconej generacji / kontroli / mapy wymagań."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services.lease_renewal import renew_lease

_APP = Path(__file__).resolve().parents[1] / "app"


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _beats(clock: _Clock, script: list, step: float = 30.0):
    calls = []

    async def beat() -> bool:
        clock.now += step
        calls.append(clock.now)
        outcome = script[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return beat, calls


@pytest.mark.asyncio
async def test_transient_error_is_retried_until_the_lease_is_really_lost():
    clock = _Clock()
    beat, calls = _beats(clock, [True, OSError("reset"), True, False])
    with pytest.raises(RuntimeError, match="lease lost"):
        await renew_lease(beat, lease_seconds=180, label="t", interval=0, clock=clock)
    # Błąd przy drugim odnowieniu nie przerwał pętli — skończyło ją jawne False.
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_errors_past_the_lease_expiry_end_the_work():
    clock = _Clock()
    beat, calls = _beats(clock, [OSError("down")] * 10, step=60.0)
    with pytest.raises(RuntimeError, match="lease expired"):
        await renew_lease(beat, lease_seconds=180, label="t", interval=0, clock=clock)
    assert len(calls) == 3


@pytest.mark.parametrize(
    "path, function",
    [
        ("services/cv_generator_b2b/durable_jobs.py", "_renew"),
        ("services/cv_approval_worker.py", "renew"),
        ("services/cv_version_map_jobs.py", "renew"),
    ],
)
def test_every_cv_worker_renews_through_the_tolerant_loop(path, function):
    tree = ast.parse((_APP / path).read_text("utf-8"))
    [node] = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == function
    ]
    called = {
        c.func.id
        for c in ast.walk(node)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
    }
    assert "renew_lease" in called
