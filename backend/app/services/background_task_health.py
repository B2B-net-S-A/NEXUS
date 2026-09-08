"""Klasyfikacja pętli w tle — jedna, współdzielona przez health i snapshot.

Do C12 istniały DWIE implementacje tej samej klasyfikacji: pełna w
``admin_snapshot._background_tasks_status`` (brała ``Request``, więc /api/health
nie mogła jej zawołać) i uboższa, wklejona wprost w handler /api/health. Rozjazd
był niewidoczny do dnia, w którym któryś z konsumentów by się zdezaktualizował.

Ta funkcja bierze SŁOWNIK zadań (nie ``Request``), więc wołają ją oba konsumenty.
Jest czysta — bez env, bez I/O — żeby dała się testować bez stawiania aplikacji.

Alarm zużycia AI działa przez powiadomienia NEXUS również bez Slacka.
Tylko zadania zależne wyłącznie od webhooka mogą kończyć się celowo przy jego
braku. Zatrzymanie alarmu AI jest awarią, a nie brakiem konfiguracji Slacka.
"""

from __future__ import annotations

import asyncio
from typing import Any

# Alarmy bramkowane na SLACK_WEBHOOK_URL (patrz docstring). Krótka, jawna lista —
# NIE dopisuj tu integracji opt-in (LinkedIn, M365, CloudTalk…): ich wyłączenie
# jest ŚWIADOME, a flagowanie go co godzinę to dokładnie ten fałszywy alarm,
# przed którym ostrzega komentarz przy uptime-probe.
SLACK_WEBHOOK_ALARM_TASKS: tuple[str, ...] = ("slack_sla_alerts",)


def classify_background_tasks(
    tasks: dict[str, "asyncio.Task[Any]"] | None,
) -> dict[str, Any]:
    """Podziel rejestr pętli na running / exited_cleanly / crashed.

    Ułamek running/expected jest z założenia nierówny (ok. połowy pętli kończy
    się celowo na własnym kill-switchu), więc jego spadek o jeden jest
    nieodróżnialny od zdrowego stanu. ``crashed`` przy zdrowej instalacji wynosi
    zero — dopiero to jest liczba, po której operator alarmuje.
    """
    if not isinstance(tasks, dict):
        return {
            "running": 0,
            "expected": 0,
            "tasks": [],
            "crashed": 0,
            "crashed_tasks": {},
            "exited_cleanly": [],
        }
    running: list[str] = []
    exited_cleanly: list[str] = []
    crashed: dict[str, str] = {}
    for name, task in tasks.items():
        if not task.done():
            running.append(name)
            continue
        if task.cancelled():
            # Anulowany = zamykanie aplikacji, nie awaria.
            exited_cleanly.append(name)
            continue
        exc = task.exception()
        if exc is None:
            # Powrót z kill-switcha — pętla nigdy nie wystartowała, i tak ma być.
            exited_cleanly.append(name)
        else:
            crashed[name] = repr(exc)
    return {
        "running": len(running),
        "expected": len(tasks),
        "tasks": sorted(running),
        "crashed": len(crashed),
        "crashed_tasks": dict(sorted(crashed.items())),
        "exited_cleanly": sorted(exited_cleanly),
    }


def stopped_webhook_alarms(
    classification: dict[str, Any], *, webhook_set: bool
) -> list[str]:
    """Krytyczne alarmy, które POWINNY biec, a cicho wyszły — realny błąd.

    Bramkowane configiem: przy nieustawionym ``SLACK_WEBHOOK_URL`` ich wyjście
    jest OCZEKIWANE (alarm jeszcze nieskonfigurowany), więc lista jest pusta i
    nic nie alarmuje. Dopiero gdy webhook JEST ustawiony, a pętla i tak wyszła
    czysto — to błąd wart issue (uptime-probe łapie prefiks ``critical:``).
    """
    if not webhook_set:
        return []
    exited = set(classification.get("exited_cleanly", []))
    return sorted(name for name in SLACK_WEBHOOK_ALARM_TASKS if name in exited)


def spend_alarm_status(classification: dict[str, Any], *, webhook_set: bool) -> str:
    """Operational health of AI alerts, independent of the optional Slack copy."""
    alarm_running = "ai_spend_alerts" in set(classification.get("tasks", []))
    if alarm_running:
        return (
            "healthy"
            if webhook_set
            else "healthy: powiadomienia NEXUS; Slack nieustawiony"
        )
    return "unhealthy: pętla alarmów zużycia AI nie biegnie"
