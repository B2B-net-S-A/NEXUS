"""Ikona „CV” w pasku (`GET /api/board-tasks/cv`): stała liczba zapytań.

18.11.2026, szczyt: 1 380 wywołań w 80 min, p95 6,7 s, 21–38 zapytań
(`docs/performance-hot-routes-2026-11-completion-report.md`). Kopia produkcji:
rekruter 4–25, Delivery Lead 14–34 zapytania, bez N+1 po wierszach. Test pilnuje,
żeby tak zostało: ta sama liczba zapytań dla 1 i 6 osób w drodze oraz górna
granica dla obu ról (z uwierzytelnieniem).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, event

from app.core.database import AsyncSessionLocal, engine
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.user import UserRole
from tests.test_board_tasks import _cleanup, _login, _seed_user, _seed_world

# Kopia produkcji 18.11 (bez auth): rekruter do 25, DL do 34. Zapas na
# uwierzytelnienie i drobne zmiany — przekroczenie to sygnał, nie szum.
RECRUITER_MAX_STATEMENTS = 32
DL_MAX_STATEMENTS = 42


@contextmanager
def _count_statements() -> Iterator[list[str]]:
    statements: list[str] = []

    def _before(_conn, _cursor, statement, *_args, **_kwargs):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _before)
    try:
        yield statements
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _before)


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _in_qc(world: dict, *, dl_id: int, rec_id: int, people: int) -> list[int]:
    """``people`` osób w „QC CV”, przekazanych przez rekrutera do tego DL."""
    now = datetime.now(timezone.utc)
    ids: list[int] = []
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.delivery_lead_id = dl_id
        job.recruiter_id = rec_id
        for index in range(people):
            unique = uuid.uuid4().hex[:8]
            cand = Candidate(
                name="Ikona",
                lastname=f"CV{index}-{unique}",
                email=f"cv-topic-{unique}@example.com",
            )
            db.add(cand)
            await db.flush()
            ids.append(cand.id)
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=world["job_id"],
                    stage="interview",
                    stage_def_id=world["defs"]["qc"],
                    moved_at=now - timedelta(hours=1, minutes=index),
                    moved_by=rec_id,
                )
            )
        await db.commit()
    return ids


async def _drop(ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id.in_(ids))
        )
        await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_cv_topic_query_count_is_constant_and_bounded(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    small, large = await _seed_world(), await _seed_world()
    dl_small, dl_small_creds = await _seed_user(UserRole.delivery_lead)
    dl_large, dl_large_creds = await _seed_user(UserRole.delivery_lead)
    rec_small, rec_small_creds = await _seed_user(UserRole.recruiter)
    rec_large, rec_large_creds = await _seed_user(UserRole.recruiter)
    small_ids = await _in_qc(small, dl_id=dl_small, rec_id=rec_small, people=1)
    large_ids = await _in_qc(large, dl_id=dl_large, rec_id=rec_large, people=6)
    try:
        headers = {
            name: await _login(api_client, creds)
            for name, creds in (
                ("dl_small", dl_small_creds),
                ("dl_large", dl_large_creds),
                ("rec_small", rec_small_creds),
                ("rec_large", rec_large_creds),
            )
        }
        # Rozgrzewka: pamięci procesu nie mogą przekłamać porównania.
        for h in headers.values():
            assert (
                await api_client.get("/api/board-tasks/cv", headers=h)
            ).status_code == 200

        counts: dict[str, int] = {}
        bodies: dict[str, dict] = {}
        for name, h in headers.items():
            with _count_statements() as statements:
                resp = await api_client.get("/api/board-tasks/cv", headers=h)
            assert resp.status_code == 200, resp.text
            counts[name] = len(statements)
            bodies[name] = resp.json()

        # Wiersze naprawdę są w odpowiedzi — inaczej porównanie nic nie mówi.
        assert (
            len(bodies["dl_large"]["dl"]["to_send"])
            + bodies["dl_large"]["dl"]["with_recruiters_total"]
            >= 6
        )
        rec_rows = bodies["rec_large"]["recruiter"]
        assert len(rec_rows["to_fix"]) + len(rec_rows["with_dl"]) >= 6

        assert counts["dl_small"] == counts["dl_large"], counts
        assert counts["rec_small"] == counts["rec_large"], counts
        assert counts["dl_large"] <= DL_MAX_STATEMENTS, counts
        assert counts["rec_large"] <= RECRUITER_MAX_STATEMENTS, counts
    finally:
        await _drop(small_ids + large_ids)
        await _cleanup(small, [dl_small, rec_small])
        await _cleanup(large, [dl_large, rec_large])
