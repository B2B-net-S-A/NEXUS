"""Które pętle w tle biegną w którym kontenerze.

Rejestr pętli jest jeden (``lifespan`` w ``main.py``), a ta lista mówi, co zostaje
w procesie danej roli. Pętla trafia do web, gdy pracuje na pamięci procesu, którą
czytają trasy albo gniazda. → docs/claude/podstawy/web-i-worker-osobno.md
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Mapping
from typing import Any

from app.core.config import settings

# Bufor licznika użycia zbierają trasy; bufory liczników wymagań, flagi korpusu,
# statystyki krytycznych i listę zaufanych UE (walidacja podpisu) czytają trasy;
# „kto jest online” i „kto ogląda” znają gniazda. Worker wczytuje listę
# w `b2b_esign_sweeper`.
WEB_ONLY_TASKS: frozenset[str] = frozenset(
    {
        "access_usage",
        "chat_email_fallback",
        "critical_stats_cache",
        "keyword_corpus_backfill",
        "presence_sync",
        "requirement_row_counts",
        "trusted_list_prewarm",
    }
)
# Opóźnienie pętli zdarzeń i odbiór zdarzeń z drugiego procesu są per proces.
EVERY_PROCESS_TASKS: frozenset[str] = frozenset({"process_bus", "runtime_metrics"})


def web_process_count() -> int:
    """Ile procesów uvicorna obsługuje HTTP obok tego (``WEB_CONCURRENCY`` czyta uvicorn).

    Tylko rola ``web`` może mieć ich kilka; worker i ``all`` zawsze 1.
    → docs/claude/podstawy/kilka-procesow-web.md
    """
    if settings.NEXUS_PROCESS_ROLE != "web":
        return 1
    try:
        return max(1, int(os.environ.get("WEB_CONCURRENCY", "1")))
    except ValueError:
        return 1


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
