"""Runda 7 (R7-V3-1): okna „z ostatnich N miesięcy” liczą od daty OTWARCIA.

`jobs.created_at` rekrutacji z Traffita to data importu (maj 2026). Lista
praktykanta i kontekst Luny na `/jobs/new` filtrowały po niej, więc archiwum
z lat 2019–2024 liczyło się jak świeży popyt.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.models.job import JobStatus
from app.services import job_similarity
from app.services.trainee_call_list import _demand_index

NOW = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)


def _job(job_id: int, *, opened_at, created_at) -> SimpleNamespace:
    return SimpleNamespace(
        id=job_id,
        skills=frozenset({"java"}),
        competence_category_id=None,
        status=JobStatus.closed.value,
        opened_at=opened_at,
        created_at=created_at,
    )


def test_demand_window_uses_opened_at_over_import_date() -> None:
    imported = NOW - timedelta(days=120)
    jobs = [
        _job(
            1, opened_at=datetime(2020, 1, 1, tzinfo=timezone.utc), created_at=imported
        ),
        _job(2, opened_at=NOW - timedelta(days=30), created_at=imported),
        _job(3, opened_at=None, created_at=NOW - timedelta(days=10)),
    ]

    index = _demand_index(jobs, {"window_months": 18}, NOW)

    assert sorted(job.id for job in index["java"]) == [2, 3]


def test_similarity_pool_carries_opened_at() -> None:
    row = SimpleNamespace(
        id=7,
        title="Java Developer",
        client_id=3,
        reference_number=None,
        status=JobStatus.published,
        competence_category_id=None,
        must_skills=["Java"],
        champion_profile=None,
        created_at=NOW,
        opened_at=datetime(2021, 5, 1, tzinfo=timezone.utc),
    )

    pool = job_similarity._build_pool([row])

    assert pool.jobs[7].opened_at == datetime(2021, 5, 1, tzinfo=timezone.utc)


def test_client_context_orders_profiles_by_opening_date() -> None:
    import inspect

    from app.services import champion_client_context

    source = inspect.getsource(champion_client_context.load_client_context)
    assert "func.coalesce(Job.opened_at, Job.created_at)" in source
    assert "Job.created_at >= since" not in source
