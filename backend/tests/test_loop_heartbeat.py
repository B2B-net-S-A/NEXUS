"""MON-04 (audyt 14.09.2026): pętla żywa, ale bez postępu, jest widoczna.

Dwie warstwy:

* ``Registry.stalled`` — pętla bez ticku dłużej niż próg (zegar wstrzykiwany,
  bez spania w testach);
* kontrakt pokrycia — każda nazwa z ``app.state.background_tasks`` jest albo
  zarejestrowana w heartbeat (``loop_heartbeat.register("nazwa"``), albo na
  liście ``EXEMPT`` z powodem. Nowa pętla bez decyzji = czerwone CI.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from app.services import loop_heartbeat

_APP = Path(__file__).parents[1] / "app"


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_live_loop_without_tick_is_stalled_after_threshold() -> None:
    clock = _Clock()
    registry = loop_heartbeat.Registry(clock=clock)
    beat = registry.register("m365", max_silence_seconds=600)
    clock.now += 599
    assert registry.stalled() == []
    clock.now += 2
    assert registry.stalled() == ["m365"]
    beat.tick()
    assert registry.stalled() == []


def test_crashed_or_finished_task_is_not_counted_as_stalled() -> None:
    clock = _Clock()
    registry = loop_heartbeat.Registry(clock=clock)
    registry.register("dead", max_silence_seconds=60)
    clock.now += 10_000
    assert registry.stalled(running={"other"}) == []
    assert registry.stalled(running={"dead"}) == ["dead"]


def test_threshold_has_a_floor() -> None:
    registry = loop_heartbeat.Registry(clock=_Clock())
    assert registry.register("x", max_silence_seconds=1).max_silence_seconds == 60


def _background_task_names() -> set[str]:
    tree = ast.parse((_APP / "main.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Dict)
            and any(
                isinstance(t, ast.Attribute) and t.attr == "background_tasks"
                for t in node.targets
            )
        ):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise AssertionError("Nie znaleziono app.state.background_tasks w main.py")


def _registered_names() -> set[str]:
    pattern = re.compile(r'loop_heartbeat\.register\(\s*"([a-z0-9_]+)"')
    names: set[str] = set()
    for path in _APP.rglob("*.py"):
        names.update(pattern.findall(path.read_text(encoding="utf-8")))
    return names


def test_every_background_task_has_a_heartbeat_decision() -> None:
    tasks = _background_task_names()
    registered = _registered_names()
    exempt = set(loop_heartbeat.EXEMPT)
    assert len(tasks) > 40
    undecided = tasks - registered - exempt
    assert not undecided, (
        f"Pętle bez decyzji o heartbeat: {sorted(undecided)} — dodaj "
        "`beat = loop_heartbeat.register(...)` + `beat.tick()` albo wpis w EXEMPT z powodem."
    )
    assert not (registered & exempt), "Pętla nie może być naraz objęta i zwolniona."
    assert not (exempt - tasks), f"Nieaktualne wpisy EXEMPT: {sorted(exempt - tasks)}"
    assert not (registered - tasks), (
        f"Heartbeat bez zadania: {sorted(registered - tasks)}"
    )
    assert all(reason.strip() for reason in loop_heartbeat.EXEMPT.values())
