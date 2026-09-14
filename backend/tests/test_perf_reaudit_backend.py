"""Poprawki po reaudycie wydajności z 14.09.2026 — backend.

- R01: `metrics.team_kpis` z jawną listą osób nie filtruje po GŁÓWNEJ roli
  (roster HoR jest ustalany po wszystkich rolach, `has_any_role`).
- R05: `release_idle_connection` oddaje połączenie tylko sesji bez zmian;
  `cache_single_flight(db=...)` zwalnia je wyłącznie przy kontencji.
- Delivery Lead N+1: `_serialize_demands` ma stałą liczbę zapytań i daje
  wynik identyczny z serializacją pojedynczego wiersza.

Testy DB używają unikalnych nazw i sprzątają po sobie — baza CI jest wspólna.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from typing import Iterator

import pytest
from sqlalchemy import delete, event, select

from app.analytics import metrics
from app.analytics.periods import resolve_period
from app.api import priority_work
from app.core.cache import cache_invalidate, cache_single_flight
from app.core.database import AsyncSessionLocal, engine, release_idle_connection
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_priority import RecruitmentPriorityDemand
from app.models.user import User, UserRole


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


# ── R01 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_team_kpis_keeps_roster_people_whose_primary_role_is_not_operational():
    tag = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        person = User(
            email=f"tcm-recruiter-{tag}@example.com",
            name=f"TCM Recruiter {tag}",
            role=UserRole.talent_community_manager,
            roles=["talent_community_manager", "recruiter"],
            is_active=True,
        )
        db.add(person)
        await db.commit()
        await db.refresh(person)
        person_id = person.id
    try:
        # Tak widzi tę osobę roster HoR (`has_any_role`).
        assert person.has_any_role(UserRole.sourcer, UserRole.recruiter, UserRole.tac)
        period = resolve_period("month")
        async with AsyncSessionLocal() as db:
            default = await metrics.team_kpis(
                db, period, user_ids=frozenset({person_id})
            )
            roster = await metrics.team_kpis(
                db,
                period,
                user_ids=frozenset({person_id}),
                operational_roles_only=False,
            )
        # Domyślne zachowanie (np. /api/analytics/v1/team/kpis) bez zmian.
        assert [row["user_id"] for row in default["rows"]] == []
        # Roster HoR: osoba jest, z zerami — nie znika z sumy.
        assert [row["user_id"] for row in roster["rows"]] == [person_id]
        assert roster["rows"][0]["first_placements"] == 0
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(User).where(User.id == person_id))
            await db.commit()


# ── R05 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_release_idle_connection_frees_a_clean_session_only():
    async with AsyncSessionLocal() as db:
        await db.execute(select(1))
        assert db.in_transaction()
        assert await release_idle_connection(db) is True
        assert not db.in_transaction()
        # Brak transakcji = nic do zwolnienia.
        assert await release_idle_connection(db) is False

    async with AsyncSessionLocal() as db:
        await db.execute(select(1))
        db.add(Client(name=f"pending-{uuid.uuid4().hex[:8]}"))
        # Niezapisana zmiana: wcześniejszy commit zmieniłby atomowość operacji.
        assert await release_idle_connection(db) is False
        assert db.in_transaction()
        await db.rollback()


class _FakeSession:
    def __init__(self) -> None:
        self.new: set[object] = set()
        self.dirty: set[object] = set()
        self.deleted: set[object] = set()
        self.commits = 0

    def in_transaction(self) -> bool:
        return True

    async def commit(self) -> None:
        self.commits += 1


@pytest.mark.asyncio
async def test_single_flight_releases_the_waiters_connection_only_under_contention():
    await cache_invalidate("reaudit:")
    uncontended = _FakeSession()
    async with cache_single_flight("reaudit:k", db=uncontended):
        pass
    # Zwykłe trafienie bez kolejki nie płaci za commit.
    assert uncontended.commits == 0

    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def _holder() -> None:
        async with cache_single_flight("reaudit:k"):
            holder_entered.set()
            await release_holder.wait()

    waiter = _FakeSession()

    async def _waiter() -> None:
        async with cache_single_flight("reaudit:k", db=waiter):
            pass

    holder = asyncio.create_task(_holder())
    await holder_entered.wait()
    waiting = asyncio.create_task(_waiter())
    await asyncio.sleep(0.01)
    # Oczekujący oddał połączenie, zanim zaczął czekać.
    assert waiter.commits == 1
    release_holder.set()
    await asyncio.gather(holder, waiting)


# ── Delivery Lead N+1 ────────────────────────────────────────────────────────


async def _seed_demands(count: int, tag: str) -> tuple[list[int], list[int], int, int]:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"ReauditClient-{tag}")
        requester = User(
            email=f"reaudit-dl-{tag}@example.com",
            name=f"Reaudit DL {tag}",
            role=UserRole.delivery_lead,
            roles=["delivery_lead"],
            is_active=True,
        )
        db.add_all([client, requester])
        await db.flush()
        jobs = [
            Job(
                title=f"ReauditJob-{tag}-{i}",
                status=JobStatus.published,
                client_id=client.id,
            )
            for i in range(count)
        ]
        db.add_all(jobs)
        await db.flush()
        demands = [
            RecruitmentPriorityDemand(
                job_id=job.id,
                requested_by_user_id=requester.id,
                rationale=f"reaudit {tag}",
            )
            for job in jobs
        ]
        db.add_all(demands)
        await db.commit()
        return (
            [d.id for d in demands],
            [j.id for j in jobs],
            client.id,
            requester.id,
        )


async def _cleanup_demands(
    demand_ids: list[int], job_ids: list[int], client_id: int, user_id: int
) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(RecruitmentPriorityDemand).where(
                RecruitmentPriorityDemand.id.in_(demand_ids)
            )
        )
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.execute(delete(Client).where(Client.id == client_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()


@pytest.mark.asyncio
async def test_batched_demand_serialization_is_constant_queries_and_matches_single():
    tag = uuid.uuid4().hex[:10]
    demand_ids, job_ids, client_id, user_id = await _seed_demands(6, tag)
    try:
        async with AsyncSessionLocal() as db:
            rows = (
                (
                    await db.execute(
                        select(RecruitmentPriorityDemand)
                        .where(RecruitmentPriorityDemand.id.in_(demand_ids))
                        .order_by(RecruitmentPriorityDemand.id)
                    )
                )
                .scalars()
                .all()
            )
            with _count_statements() as one:
                await priority_work._serialize_demands(
                    db, rows[:1], current_assignments=[]
                )
            with _count_statements() as six:
                batched = await priority_work._serialize_demands(
                    db, rows, current_assignments=[]
                )
            single = [
                await priority_work._serialize_demand(db, row, current_assignments=[])
                for row in rows
            ]
        # Liczba zapytań nie rośnie z liczbą demandów.
        assert len(six) == len(one)
        assert batched == single
        assert {item["requested_by_name"] for item in batched} == {f"Reaudit DL {tag}"}
        assert all(
            item["job"]["client_name"] == f"ReauditClient-{tag}" for item in batched
        )
    finally:
        await _cleanup_demands(demand_ids, job_ids, client_id, user_id)
