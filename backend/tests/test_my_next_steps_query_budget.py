"""``GET /api/pipeline/my-next-steps`` — stała liczba zapytań, te same tablice.

18.11.2026 na produkcji trasa miała p95 36,7 s przy średnio 400 zapytaniach:
składała do 25 tablic po jednej (`build_kanban_view` ok. 47 zapytań każda).
Na kopii produkcji: 791–1363 zapytań. Tablice ładuje teraz jeden zestaw zapytań
(`build_kanban_views`), więc liczba nie zależy od liczby rekrutacji — a każda
tablica jest tą samą, którą zwraca pojedyncza Tablica.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
import pytest
from httpx import AsyncClient
from sqlalchemy import event

from app.core.database import AsyncSessionLocal, engine
from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole

URL = "/api/pipeline/my-next-steps"

_BOARD_FLAGS = dict(
    with_followups=False,
    with_employment=False,
    with_start_docs=False,
    with_cv_state=False,
    with_other_jobs=False,
)


@contextmanager
def _count_sql():
    seen: list[str] = []

    def _on(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on)


async def _seed_user() -> tuple[dict, int]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"mns-budget-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Budget"),
            name=f"MNS Budget {tag}",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    return {"Authorization": f"Bearer {create_access_token(uid, 'recruiter')}"}, uid


async def _seed_boards(owner_id: int, count: int) -> tuple[list[int], int]:
    """``count`` rekrutacji osoby, każda u innego klienta, z kartami w kilku
    etapach (także „Zatrudniony” i „Odrzucony”). Jedna osoba stoi na KAŻDEJ
    tablicy, na każdej w innym etapie i z próbą kontaktu tylko w pierwszej."""
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.note import Note
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services import note_kinds

    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    stages = (
        PipelineStage.new,
        PipelineStage.screening,
        PipelineStage.verified,
        PipelineStage.hired,
        PipelineStage.rejected,
    )
    async with AsyncSessionLocal() as db:
        shared = Candidate(
            name="Wspólna",
            lastname=f"Osoba-{tag}",
            email=f"mns-shared-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add(shared)
        job_ids: list[int] = []
        for j in range(count):
            client = Client(name=f"MNSBudget-{tag}-{j}")
            db.add(client)
            await db.flush()
            job = Job(
                title=f"MNSBudget-{tag}-{j}",
                status=JobStatus.published,
                client_id=client.id,
                recruiter_id=owner_id,
                # Rosnący termin = stała kolejność tablic w odpowiedzi.
                deadline=(now + timedelta(days=j + 1)).date(),
            )
            db.add(job)
            await db.flush()
            job_ids.append(job.id)
            people = [
                Candidate(
                    name="Jan",
                    lastname=f"MNSBudget-{tag}-{j}-{i}",
                    email=f"mns-{tag}-{j}-{i}@example.com",
                    status=CandidateStatus.active,
                )
                for i in range(len(stages))
            ]
            db.add_all(people)
            await db.flush()
            for i, (person, stage) in enumerate(zip(people, stages)):
                db.add(
                    CandidateStage(
                        candidate_id=person.id,
                        job_id=job.id,
                        stage=stage,
                        moved_by=owner_id,
                        moved_at=now - timedelta(days=3, minutes=i),
                    )
                )
            db.add(
                CandidateStage(
                    candidate_id=shared.id,
                    job_id=job.id,
                    stage=stages[j % len(stages)],
                    moved_by=owner_id,
                    moved_at=now - timedelta(days=1, minutes=j),
                )
            )
        await db.flush()
        db.add(
            Note(
                candidate_id=shared.id,
                job_id=job_ids[0],
                kind=note_kinds.CONTACT_ATTEMPT,
                content="Nie odebrał",
                author_id=owner_id,
            )
        )
        await db.commit()
        return job_ids, shared.id


async def _call(app_client: AsyncClient, headers: dict) -> tuple[dict, int]:
    with _count_sql() as seen:
        resp = await app_client.get(URL, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json(), len(seen)


@pytest.mark.asyncio
async def test_query_count_does_not_grow_with_boards(app_client: AsyncClient):
    small_headers, small_uid = await _seed_user()
    big_headers, big_uid = await _seed_user()
    await _seed_boards(small_uid, 2)
    await _seed_boards(big_uid, 6)
    # Rozgrzewka: pierwsze żądanie procesu czyta jednorazowo ustawienia.
    await _call(app_client, small_headers)

    small, small_n = await _call(app_client, small_headers)
    big, big_n = await _call(app_client, big_headers)

    assert len(small["jobs"]) == 2
    assert len(big["jobs"]) == 6
    # Przed 19.11.2026: ok. 40 zapytań więcej na każdą tablicę.
    assert big_n == small_n, (small_n, big_n)


@pytest.mark.asyncio
async def test_each_board_is_the_single_board_view(app_client: AsyncClient):
    """Hurt nie miesza tablic: ta sama osoba na trzech rekrutacjach ma na każdej
    swój etap i swoje próby kontaktu, a tablica = `build_kanban_view` tej
    rekrutacji z tymi samymi flagami."""
    from app.api.pipeline import build_kanban_view
    from app.models.job import Job

    headers, uid = await _seed_user()
    job_ids, shared_id = await _seed_boards(uid, 3)

    body, _ = await _call(app_client, headers)
    by_job = {entry["job_id"]: entry["view"] for entry in body["jobs"]}
    assert set(by_job) == set(job_ids)

    async with AsyncSessionLocal() as db:
        user = await db.get(User, uid)
        for job_id in job_ids:
            job = await db.get(Job, job_id)
            single = await build_kanban_view(db, job, viewer=user, **_BOARD_FLAGS)
            expected = single.model_dump(mode="json")
            got = by_job[job_id]
            # Zegar: „dni na etapie” liczy się od chwili żądania.
            for view in (expected, got):
                for col in view["columns"]:
                    for item in col["items"]:
                        item.pop("days_in_stage", None)
            assert got == expected, job_id

    shared_cards = {
        job_id: [
            item
            for col in view["columns"]
            for item in col["items"]
            if item["candidate_id"] == shared_id
        ]
        for job_id, view in by_job.items()
    }
    assert all(len(cards) == 1 for cards in shared_cards.values()), shared_cards
    attempts = {
        job_id: cards[0]["contact_attempts"] for job_id, cards in shared_cards.items()
    }
    assert attempts == {job_ids[0]: 1, job_ids[1]: 0, job_ids[2]: 0}


@pytest.mark.asyncio
async def test_batches_give_the_same_boards(
    app_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """Suma kart ponad próg (`KANBAN_BATCH_MAX_CARDS`, limit parametrów asyncpg)
    dzieli tablice na porcje — odpowiedź ta sama co jedną porcją."""
    from app.api import pipeline as pipeline_api

    headers, uid = await _seed_user()
    await _seed_boards(uid, 4)
    whole, whole_n = await _call(app_client, headers)
    # 6 kart na tablicę: próg 12 = dwie tablice w porcji.
    monkeypatch.setattr(pipeline_api, "KANBAN_BATCH_MAX_CARDS", 12)
    split, split_n = await _call(app_client, headers)

    def _stable(body: dict) -> dict:
        for entry in body["jobs"]:
            for col in entry["view"]["columns"]:
                for item in col["items"]:
                    item.pop("days_in_stage", None)
        return body

    assert _stable(split) == _stable(whole)
    assert split_n > whole_n


@pytest.mark.asyncio
async def test_delivery_lead_activity_read_once(app_client: AsyncClient):
    """Delivery Lead z rekrutacjami innych DL-ów: aktywność każdego z nich
    nie jest osobnym zapytaniem na tablicę."""
    from app.models.job import Job

    async def _dl_with_boards(count: int) -> dict:
        tag = uuid.uuid4().hex[:8]
        async with AsyncSessionLocal() as db:
            viewer = User(
                email=f"mns-dl-{tag}@example.com",
                password_hash=hash_password(f"T3st_{tag}!Dl"),
                name=f"MNS DL {tag}",
                role=UserRole.delivery_lead,
                is_active=True,
            )
            others = [
                User(
                    email=f"mns-dl-other-{tag}-{i}@example.com",
                    password_hash=hash_password(f"T3st_{tag}!Other{i}"),
                    name=f"MNS DL other {tag} {i}",
                    role=UserRole.delivery_lead,
                    is_active=i % 2 == 0,
                )
                for i in range(count)
            ]
            db.add_all([viewer, *others])
            await db.commit()
            viewer_id = viewer.id
            other_ids = [o.id for o in others]
        job_ids, _ = await _seed_boards(viewer_id, count)
        async with AsyncSessionLocal() as db:
            for job_id, dl_id in zip(job_ids, other_ids):
                job = await db.get(Job, job_id)
                job.delivery_lead_id = dl_id
            await db.commit()
        return {
            "Authorization": f"Bearer {create_access_token(viewer_id, 'delivery_lead')}"
        }

    small = await _dl_with_boards(2)
    big = await _dl_with_boards(5)
    await _call(app_client, small)
    small_body, small_n = await _call(app_client, small)
    big_body, big_n = await _call(app_client, big)

    assert len(small_body["jobs"]) == 2
    assert len(big_body["jobs"]) == 5
    assert big_n == small_n, (small_n, big_n)
