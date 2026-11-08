"""Runda 7 (R7-V3-1): okna „z ostatnich N miesięcy” liczą od daty OTWARCIA.

`jobs.created_at` rekrutacji z Traffita to data importu (maj 2026). Lista
praktykanta i kontekst Luny na `/jobs/new` filtrowały po niej, więc archiwum
z lat 2019–2024 liczyło się jak świeży popyt.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from app.models.job import JobStatus
from app.services import job_similarity

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
