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


_TASK_FACTORIES = {"create_task", "ensure_future"}

# Moduły spoza `app/api`, które tworzą zadania same — każdy z powodem, dla
# którego referencja jest trzymana (albo zadanie jest awaitowane). Nowy moduł
# ma użyć `spawn`, a nie dopisać się tutaj bez powodu.
_ALLOWED_OUTSIDE_API = {
    "app/main.py": "pętle z lifespan — słownik `app.state.background_tasks`, "
    "nadzór i anulowanie przy zamknięciu",
    "app/services/order_mail_ingest.py": "`start_ingest_task` zwraca zadanie "
    "(trasa czeka na jego start) i trzyma je w `_bg_tasks`",
    "app/services/academy.py": "`_background` + `wait_for_background` "
    "(testy i łagodne zamknięcie czekają na sortowanie)",
    "app/services/experience_backfill.py": "`_TASKS` + rezerwacja `_IN_FLIGHT` "
    "zwalniana, gdy pętli nie ma",
    "app/services/cv_approval_worker.py": "worker: heartbeat i zadania w "
    "słowniku `active`, awaitowane/anulowane w pętli",
    "app/services/cv_version_map_jobs.py": "worker: heartbeat i zadania w "
    "słowniku `active`, awaitowane/anulowane w pętli",
    "app/services/cv_generator_b2b/durable_jobs.py": "worker: odnowienie "
    "dzierżawy i zadania w pętli, awaitowane/anulowane",
    "app/services/jarvis/agent.py": "`ensure_future` na wywołaniu modelu i "
    "kolejce delt — oba awaitowane w tej samej turze",
}


def _task_factory_calls(tree: ast.AST) -> list[tuple[int, bool]]:
    """(linia, czy wynik wyrzucony) dla każdego `*.create_task`/`ensure_future`."""
    parents = {
        child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
    }
    found: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in _TASK_FACTORIES
        ):
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Await):
            parent = parents.get(parent)
        found.append((node.lineno, isinstance(parent, ast.Expr)))
    return found


def _app_modules() -> list[Path]:
    return sorted(
        path
        for path in (_BACKEND / "app").rglob("*.py")
        if path != _BACKEND / "app/core/tasks.py"
    )


def test_no_background_task_is_created_outside_spawn() -> None:
    """Skan CAŁEGO `app/` (audyt 25.09.2026, runda 2).

    Do rundy 2 test sprawdzał pięć wymienionych modułów, a goły
    `asyncio.create_task` żył dalej w backfillu pul talentów, notatkach,
    backfillu procesów rekrutacji i powiadomieniu Teams po dodaniu kandydata.
    Lista modułów przegrywa z każdym nowym endpointem — skan nie.

    * trasy (`app/api`) nie tworzą zadań w ogóle — tylko przez `spawn`;
    * nigdzie wynik `create_task` nie jest wyrzucany (to jest zgubiona
      referencja, którą GC może zebrać w połowie biegu);
    * poza trasami zadania tworzą tylko moduły z listy wyjątków (z powodem).
    """
    offenders: list[str] = []
    seen_allowed: set[str] = set()
    for path in _app_modules():
        rel = path.relative_to(_BACKEND).as_posix()
        calls = _task_factory_calls(ast.parse(path.read_text(encoding="utf-8")))
        if not calls:
            continue
        for lineno, discarded in calls:
            if discarded:
                offenders.append(f"{rel}:{lineno} wynik wyrzucony — użyj spawn()")
            elif rel.startswith("app/api/"):
                offenders.append(f"{rel}:{lineno} trasa tworzy zadanie — użyj spawn()")
            elif rel not in _ALLOWED_OUTSIDE_API:
                offenders.append(
                    f"{rel}:{lineno} zadanie poza spawn() — użyj spawn() albo "
                    "dopisz moduł do _ALLOWED_OUTSIDE_API z powodem"
                )
        seen_allowed.add(rel)
    assert offenders == [], "\n".join(offenders)
    stale = sorted(set(_ALLOWED_OUTSIDE_API) - seen_allowed)
    assert stale == [], f"wyjątki bez create_task — usuń je z listy: {stale}"


def test_discarded_create_task_is_detected() -> None:
    """Skaner łapie dokładnie ten wzorzec, który pilnuje (bez tego test
    wyżej mógłby przechodzić, niczego nie znajdując)."""
    tree = ast.parse(
        "async def f():\n"
        "    asyncio.create_task(g())\n"
        "    task = asyncio.create_task(g())\n"
        "    loop.create_task(g())\n"
    )
    assert _task_factory_calls(tree) == [(2, True), (3, False), (4, True)]
