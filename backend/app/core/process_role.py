"""Które pętle w tle biegną w którym kontenerze.

Rejestr pętli jest jeden (``lifespan`` w ``main.py``), a ta lista mówi, co zostaje
w procesie danej roli. Pętla trafia do web, gdy pracuje na pamięci procesu, którą
czytają trasy albo gniazda. → docs/claude/podstawy/web-i-worker-osobno.md
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

# Bufor licznika użycia zbierają trasy; bufory liczników wymagań, flagi korpusu
# i statystyki krytycznych czytają trasy; „kto jest online” znają gniazda.
WEB_ONLY_TASKS: frozenset[str] = frozenset(
    {
        "access_usage",
        "chat_email_fallback",
        "critical_stats_cache",
        "keyword_corpus_backfill",
        "requirement_row_counts",
    }
)
# Opóźnienie pętli zdarzeń i odbiór zdarzeń z drugiego procesu są per proces.
EVERY_PROCESS_TASKS: frozenset[str] = frozenset({"process_bus", "runtime_metrics"})


def task_runs_in_role(name: str, role: str) -> bool:
    if role == "web":
        return name in WEB_ONLY_TASKS or name in EVERY_PROCESS_TASKS
    if role == "worker":
        return name not in WEB_ONLY_TASKS
    return True


def keep_tasks_for_role(
    tasks: Mapping[str, "asyncio.Task[Any]"], role: str
) -> dict[str, "asyncio.Task[Any]"]:
    """Anuluj pętle innej roli przed pierwszym ``await``: nie wykonają ani linii."""
    kept: dict[str, "asyncio.Task[Any]"] = {}
    for name, task in tasks.items():
        if task_runs_in_role(name, role):
            kept[name] = task
        else:
            task.cancel()
    return kept
