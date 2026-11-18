"""``GET /api/candidates/{id}/recommendations`` — stała liczba zapytań.

18.11.2026 na produkcji jedno wejście w profil kandydata robiło 356 zapytań:
ocena każdej rekrutacji z puli pytała osobno o screening pary i o konflikt
z klientem (`score_candidate_job` bez `context`). Trasa buduje teraz oba
hurtem (`build_jobs_scoring_contexts`), więc liczba zapytań nie zależy od
wielkości puli — i ostrzeżenie o konflikcie dalej trafia do właściwej oferty.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from httpx import AsyncClient
from sqlalchemy import event

from app.api import recommendations as rec_api
from app.core.database import AsyncSessionLocal, engine
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.job import Job, JobStatus

pytestmark = pytest.mark.asyncio


@contextmanager
def count_statements():
    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


async def _seed(job_count: int) -> tuple[int, list[int], int]:
    """Kandydat + `job_count` opublikowanych rekrutacji, każda u innego klienta.

    Konflikt kandydata z klientem pierwszej rekrutacji.
    """
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Rec{suffix}",
            lastname="Budget",
            competence_category="Java",
            skills=[{"name": "Java"}],
        )
        clients = [Client(name=f"RecBudget {suffix} {i}") for i in range(job_count)]
        db.add(cand)
        db.add_all(clients)
        await db.flush()
        jobs = [
            Job(
                title=f"Java Developer {suffix} {i}",
                client_id=c.id,
                status=JobStatus.published,
            )
            for i, c in enumerate(clients)
        ]
        db.add_all(jobs)
        db.add(
            CandidateConflict(
                candidate_id=cand.id,
                client_id=clients[0].id,
                type=ConflictType.nda,
                active=True,
            )
        )
        await db.commit()
        return cand.id, [j.id for j in jobs], jobs[0].id


async def _call(
    app_client: AsyncClient,
    headers: dict,
    monkeypatch: pytest.MonkeyPatch,
    candidate_id: int,
    job_ids: list[int],
) -> tuple[dict, int]:
    async def fake_search(query, top_k=20, **kwargs):
        return [{"job_id": jid, "score": 0.8} for jid in job_ids]

    monkeypatch.setattr(rec_api, "search_jobs_semantic", fake_search)
    with count_statements() as seen:
        resp = await app_client.get(
            f"/api/candidates/{candidate_id}/recommendations",
            params={"top_k": 50},
            headers=headers,
        )
    assert resp.status_code == 200, resp.text
    return resp.json(), len(seen)


async def test_query_count_does_not_grow_with_pool(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch: pytest.MonkeyPatch
):
    small_cand, small_jobs, _ = await _seed(3)
    big_cand, big_jobs, _ = await _seed(12)
    # Rozgrzewka: pierwsze żądanie procesu czyta jednorazowo ustawienia.
    await _call(app_client, app_auth_headers, monkeypatch, small_cand, small_jobs)

    small, small_n = await _call(
        app_client, app_auth_headers, monkeypatch, small_cand, small_jobs
    )
    big, big_n = await _call(
        app_client, app_auth_headers, monkeypatch, big_cand, big_jobs
    )

    assert len(small["matches"]) == 3
    assert len(big["matches"]) == 12
    # Przed 18.11.2026: +2 zapytania na każdą rekrutację z puli (18 różnicy).
    assert big_n == small_n, (small_n, big_n)


async def test_conflict_warning_stays_on_its_job(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch: pytest.MonkeyPatch
):
    cand, jobs, conflicted_job = await _seed(4)
    body, _ = await _call(app_client, app_auth_headers, monkeypatch, cand, jobs)

    warned = {
        m["job"]["id"]
        for m in body["matches"]
        if "active_conflict" in (m["breakdown"].get("warnings") or [])
    }
    assert warned == {conflicted_job}
