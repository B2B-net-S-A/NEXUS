"""Nowa rekrutacja zaczyna od P1 (decyzja Artura 08.10.2026).

Domyślny priorytet ma dwa miejsca: schemat ``POST /api/jobs`` (klient API,
który pola nie wysyła) i przełącznik na ``/jobs/new`` (front wysyła pole
zawsze). Rozjazd dałby inną rekrutację z formularza niż z API, więc poziom
czytamy z jednej funkcji i pilnujemy lustra frontu.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.models.job import JobPriority
from app.schemas.job import JobCreate
from app.services.job_priority import (
    NEW_JOB_PRIORITY_LEVEL,
    default_priority_for_new_job,
    level_of,
    priority_rank,
)

REPO = Path(__file__).resolve().parents[2]
FRONT = REPO / "frontend" / "src" / "lib" / "request-priority.ts"


def _create(**fields) -> JobCreate:
    # Komplet wymagany od „Rekrutacji bez szkiców” (04.10.2026).
    return JobCreate(
        title="Java Developer",
        client_id=1,
        champion_profile={},
        hiring_manager={"not_provided": True},
        handoff={"recruiter_id": 5},
        **fields,
    )


def test_new_job_without_priority_gets_p1():
    created = _create()

    assert created.priority is JobPriority.urgent
    assert level_of(created.priority) == "p1"
    # P1 idzie pierwsze w kolejce automatu przydziału.
    assert priority_rank(created.priority) == 0


def test_default_function_and_level_agree():
    assert NEW_JOB_PRIORITY_LEVEL == "p1"
    assert level_of(default_priority_for_new_job()) == NEW_JOB_PRIORITY_LEVEL


def test_explicit_priority_is_kept():
    for value, level in (("medium", "p2"), ("low", "accepting"), ("urgent", "p1")):
        created = _create(priority=value)
        assert level_of(created.priority) == level


def test_front_starts_new_job_from_the_same_level():
    match = re.search(
        r'export const NEW_JOB_PRIORITY_LEVEL: PriorityLevel = "([a-z0-9]+)"',
        FRONT.read_text(),
    )
    assert match, "brak NEW_JOB_PRIORITY_LEVEL w request-priority.ts"
    assert match.group(1) == NEW_JOB_PRIORITY_LEVEL
