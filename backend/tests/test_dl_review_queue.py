"""Porównanie kolejki przeglądu DL w jednej rekrutacji (D10, 08.10.2026).

`GET /api/dl-review/jobs/{id}/queue` — osoby w „QC CV” jednej rekrutacji obok
siebie: ocena rekrutera, wymagania X/Y, koszt, start, ryzyka, ile czeka.
Ten sam builder co kontekst przeglądu, stała liczba zapytań niezależnie od
liczby osób; u Nordei pusto (CV idzie do Cpro).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

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


async def _fill_qc(world: dict, dl_id: int, people: int) -> list[int]:
    """``people`` osób w „QC CV” rekrutacji świata (ze stawką i arkuszem)."""
    now = datetime.now(timezone.utc)
    ids: list[int] = []
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, world["job_id"])
        job.delivery_lead_id = dl_id
        job.must_skills = ["Java"]
        for index in range(people):
            unique = uuid.uuid4().hex[:8]
            cand = Candidate(
                name="Kolejka",
                lastname=f"DLQ{index}-{unique}",
                email=f"dlq-{unique}@example.com",
                raw_cv_text="Java i Spring, 5 lat.",
            )
            db.add(cand)
            await db.flush()
            ids.append(cand.id)
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=world["job_id"],
                    stage="verified",
                    stage_def_id=world["defs"]["verified"],
                    moved_at=now - timedelta(hours=3),
                    expected_rate_value=Decimal("140"),
                    expected_rate_unit="hourly",
                    expected_rate_currency="PLN",
                    # Arkusz bez odpowiedzi nie jest wypełniony (`sheet_filled`).
                    screening_answers={
                        "answers": [{"question_id": "q1", "response": "Java 5 lat"}],
                        "overall_fit": "fit",
                    },
                )
            )
            db.add(
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=world["job_id"],
                    stage="interview",
                    stage_def_id=world["defs"]["qc"],
                    moved_at=now - timedelta(hours=1, minutes=index),
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
async def test_queue_lists_people_in_qc_with_constant_queries(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", "")
    small, large = await _seed_world(), await _seed_world()
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    rec_id, rec_creds = await _seed_user(UserRole.recruiter)
    small_ids = await _fill_qc(small, dl_id, 3)
    large_ids = await _fill_qc(large, dl_id, 10)
    try:
        dl = await _login(api_client, dl_creds)
        rec = await _login(api_client, rec_creds)
        denied = await api_client.get(
            f"/api/dl-review/jobs/{small['job_id']}/queue", headers=rec
        )
        assert denied.status_code == 403

        # Rozgrzewka: pamięci procesu (statystyki krytycznych, słownik
        # umiejętności) nie mogą przekłamać porównania liczby zapytań.
        await api_client.get(f"/api/dl-review/jobs/{small['job_id']}/queue", headers=dl)
        counts = []
        for world, expected in ((small, 3), (large, 10)):
            with _count_statements() as statements:
                resp = await api_client.get(
                    f"/api/dl-review/jobs/{world['job_id']}/queue", headers=dl
                )
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert body["cpro_client"] is False
            assert body["total"] == expected
            assert len(body["items"]) == expected
            item = body["items"][0]
            assert item["requirements_total"] == 1
            assert item["requirements_met"] == 1
            assert item["candidate_rate"]["hourly_pln"] == 140.0
            assert item["overall_fit"] == "fit"
            assert item["task"]["kind"] == "dl_review"
            counts.append(len(statements))
        assert counts[0] == counts[1], counts
    finally:
        await _drop(small_ids + large_ids)
        await _cleanup(small, [dl_id, rec_id])
        await _cleanup(large, [])


@pytest.mark.asyncio
async def test_nordea_queue_is_empty(
    api_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _seed_world()
    monkeypatch.setenv("NORDEA_ORDER_NUMBER_CLIENT_IDS", str(world["client_id"]))
    dl_id, dl_creds = await _seed_user(UserRole.delivery_lead)
    ids = await _fill_qc(world, dl_id, 2)
    try:
        dl = await _login(api_client, dl_creds)
        resp = await api_client.get(
            f"/api/dl-review/jobs/{world['job_id']}/queue", headers=dl
        )
        assert resp.status_code == 200, resp.text
        assert resp.json() == {
            "job_id": world["job_id"],
            "cpro_client": True,
            "items": [],
            "total": 0,
            "limit": 50,
        }
    finally:
        await _drop(ids)
        await _cleanup(world, [dl_id])
