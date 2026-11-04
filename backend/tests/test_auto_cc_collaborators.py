"""Uczestnicy rekrutacji z kategorii kompetencji (``source='auto_cc'``).

Reguła: uczestnikami są WSZYSTKIE osoby kategorii rekrutacji (1. i 2.
priorytet), a synchronizacja nie rusza wierszy ręcznych, osób zdjętych
z rekrutacji ani rekrutacji zamkniętych. Każdy test pracuje na własnej
kategorii — baza testowa jest wspólna i nie jest czyszczona.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.client import Client
from app.models.competence_category import (
    CompetenceCategory,
    UserCompetenceCategory,
)
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.user import User, UserRole
from app.services.auto_cc_collaborators import (
    category_member_ids,
    participants_count,
    sync_cc_participants,
)

pytestmark = pytest.mark.asyncio


class _World:
    """Dane jednego testu + sprzątanie po nim."""

    def __init__(self) -> None:
        self.user_ids: list[int] = []
        self.job_ids: list[int] = []
        self.category_ids: list[int] = []
        self.client_ids: list[int] = []

    async def category(self) -> int:
        tag = uuid.uuid4().hex[:8]
        async with AsyncSessionLocal() as db:
            row = CompetenceCategory(
                slug=f"autocc-{tag}",
                name_pl=f"Kategoria {tag}",
                name_en=f"Category {tag}",
                description="kategoria testowa uczestników",
                keywords=[],
                is_active=True,
                display_order=99,
            )
            db.add(row)
            await db.commit()
            self.category_ids.append(row.id)
            return row.id

    async def person(
        self,
        category_id: int | None,
        *,
        priority: int = 1,
        role: UserRole = UserRole.recruiter,
        roles: list[str] | None = None,
        active: bool = True,
    ) -> int:
        tag = uuid.uuid4().hex[:8]
        async with AsyncSessionLocal() as db:
            user = User(
                email=f"autocc-{tag}@example.com",
                password_hash=hash_password(f"P@ss-{tag}"),
                name=f"AutoCC {tag}",
                role=role,
                roles=roles if roles is not None else [role.value],
                is_active=active,
            )
            db.add(user)
            await db.flush()
            if category_id is not None:
                db.add(
                    UserCompetenceCategory(
                        user_id=user.id,
                        competence_category_id=category_id,
                        priority=priority,
                        is_primary=priority == 1,
                    )
                )
            await db.commit()
            self.user_ids.append(user.id)
            return user.id

    async def job(
        self,
        category_id: int | None,
        *,
        status: JobStatus = JobStatus.published,
        work_state: str = "searching",
    ) -> int:
        tag = uuid.uuid4().hex[:8]
        async with AsyncSessionLocal() as db:
            client = Client(name=f"AutoCC klient {tag}")
            db.add(client)
            await db.flush()
            job = Job(
                title=f"AutoCC rekrutacja {tag}",
                status=status,
                work_state=work_state,
                client_id=client.id,
                competence_category_id=category_id,
            )
            db.add(job)
            await db.commit()
            self.client_ids.append(client.id)
            self.job_ids.append(job.id)
            return job.id

    async def cleanup(self) -> None:
        async with AsyncSessionLocal() as db:
            if self.job_ids:
                await db.execute(delete(Job).where(Job.id.in_(self.job_ids)))
            if self.client_ids:
                await db.execute(delete(Client).where(Client.id.in_(self.client_ids)))
            if self.user_ids:
                await db.execute(delete(User).where(User.id.in_(self.user_ids)))
            if self.category_ids:
                await db.execute(
                    delete(CompetenceCategory).where(
                        CompetenceCategory.id.in_(self.category_ids)
                    )
                )
            await db.commit()


@pytest_asyncio.fixture
async def world():
    data = _World()
    yield data
    await data.cleanup()


async def _rows(job_id: int) -> dict[int, tuple[str, bool]]:
    """``{osoba: (źródło, zdjęta)}`` dla rekrutacji."""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    JobCollaborator.user_id,
                    JobCollaborator.source,
                    JobCollaborator.removed_from_auto_cc,
                ).where(JobCollaborator.job_id == job_id)
            )
        ).all()
    return {user_id: (source.value, removed) for user_id, source, removed in rows}


async def _sync(**kwargs) -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        result = await sync_cc_participants(db, **kwargs)
        await db.commit()
        return result


async def _add_row(job_id: int, user_id: int, *, source: str, removed: bool = False):
    async with AsyncSessionLocal() as db:
        db.add(
            JobCollaborator(
                job_id=job_id,
                user_id=user_id,
                source=JobCollaboratorSource(source),
                removed_from_auto_cc=removed,
            )
        )
        await db.commit()


async def test_both_priorities_become_participants(world: _World) -> None:
    category = await world.category()
    first = await world.person(category, priority=1)
    second = await world.person(category, priority=2)
    recruiter = await world.person(category, priority=1, role=UserRole.recruiter)
    job = await world.job(category)

    result = await _sync(job_ids=[job])

    assert result == {"added": 3, "removed": 0}
    assert await _rows(job) == {
        first: ("auto_cc", False),
        second: ("auto_cc", False),
        recruiter: ("auto_cc", False),
    }
    # Drugi przebieg nic nie zmienia.
    assert await _sync(job_ids=[job]) == {"added": 0, "removed": 0}
    assert len(await _rows(job)) == 3


async def test_only_active_operators_of_the_category_are_added(world: _World) -> None:
    category = await world.category()
    other_category = await world.category()
    member = await world.person(category)
    # Delivery Lead z dodatkową rolą rekrutera jest osobą kategorii.
    hybrid = await world.person(
        category,
        role=UserRole.delivery_lead,
        roles=["delivery_lead", "recruiter"],
    )
    await world.person(category, role=UserRole.delivery_lead)
    await world.person(category, active=False)
    await world.person(other_category)
    await world.person(None)
    job = await world.job(category)

    await _sync(job_ids=[job])

    assert set(await _rows(job)) == {member, hybrid}
    async with AsyncSessionLocal() as db:
        members = await category_member_ids(db, [category, other_category])
        counts = await participants_count(db, [category, other_category])
    assert members[category] == {member, hybrid}
    assert counts[category] == 2
    assert counts[other_category] == 1


async def test_sync_leaves_manual_rows_alone(world: _World) -> None:
    category = await world.category()
    member = await world.person(category)
    outsider = await world.person(None)
    job = await world.job(category)
    await _add_row(job, member, source="manual")
    await _add_row(job, outsider, source="manual")

    result = await _sync(job_ids=[job])

    assert result == {"added": 0, "removed": 0}
    assert await _rows(job) == {
        member: ("manual", False),
        outsider: ("manual", False),
    }


async def test_person_removed_from_the_job_is_not_added_again(world: _World) -> None:
    category = await world.category()
    removed = await world.person(category)
    kept = await world.person(category, priority=2)
    job = await world.job(category)
    await _add_row(job, removed, source="auto_cc", removed=True)

    result = await _sync(job_ids=[job])

    assert result == {"added": 1, "removed": 0}
    assert await _rows(job) == {
        removed: ("auto_cc", True),
        kept: ("auto_cc", False),
    }
    # Także przebieg po całej kategorii (pętla godzinna) tej osoby nie wraca.
    await _sync(category_ids=[category])
    assert (await _rows(job))[removed] == ("auto_cc", True)


async def test_category_change_swaps_participants(world: _World) -> None:
    old_category = await world.category()
    new_category = await world.category()
    old_member = await world.person(old_category)
    both = await world.person(old_category)
    new_member = await world.person(new_category)
    async with AsyncSessionLocal() as db:
        db.add(
            UserCompetenceCategory(
                user_id=both,
                competence_category_id=new_category,
                priority=2,
                is_primary=False,
            )
        )
        await db.commit()
    manual = await world.person(old_category)
    job = await world.job(old_category)
    await _add_row(job, manual, source="manual")
    await _sync(job_ids=[job])
    assert set(await _rows(job)) == {old_member, both, manual}

    async with AsyncSessionLocal() as db:
        row = await db.get(Job, job)
        row.competence_category_id = new_category
        await db.flush()
        result = await sync_cc_participants(db, job_ids=[job])
        await db.commit()

    assert result == {"added": 1, "removed": 1}
    assert await _rows(job) == {
        both: ("auto_cc", False),
        new_member: ("auto_cc", False),
        manual: ("manual", False),
    }


async def test_leaving_the_category_removes_rows_on_open_jobs_only(
    world: _World,
) -> None:
    category = await world.category()
    leaving = await world.person(category)
    staying = await world.person(category, priority=2)
    open_job = await world.job(category)
    draft_job = await world.job(
        category, status=JobStatus.draft, work_state="to_review"
    )
    await _sync(category_ids=[category])
    # Rekrutacje zamknięta i „Zakończona” niosą listę z czasu, gdy były otwarte.
    closed_job = await world.job(category, status=JobStatus.closed)
    finished_job = await world.job(category, work_state="finished")
    for job in (closed_job, finished_job):
        await _add_row(job, leaving, source="auto_cc")

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(UserCompetenceCategory).where(
                UserCompetenceCategory.user_id == leaving,
                UserCompetenceCategory.competence_category_id == category,
            )
        )
        await db.flush()
        result = await sync_cc_participants(db, category_ids=[category])
        await db.commit()

    assert result == {"added": 0, "removed": 2}
    assert await _rows(open_job) == {staying: ("auto_cc", False)}
    assert await _rows(draft_job) == {staying: ("auto_cc", False)}
    # Zamkniętych synchronizacja nie rusza — ani nie zdejmuje, ani nie dodaje.
    assert await _rows(closed_job) == {leaving: ("auto_cc", False)}
    assert await _rows(finished_job) == {leaving: ("auto_cc", False)}


async def test_job_without_category_loses_category_participants(world: _World) -> None:
    category = await world.category()
    member = await world.person(category)
    manual = await world.person(None)
    job = await world.job(category)
    await _add_row(job, manual, source="manual")
    await _sync(job_ids=[job])
    assert set(await _rows(job)) == {member, manual}

    async with AsyncSessionLocal() as db:
        row = await db.get(Job, job)
        row.competence_category_id = None
        await db.flush()
        result = await sync_cc_participants(db, job_ids=[job])
        await db.commit()

    assert result == {"added": 0, "removed": 1}
    assert await _rows(job) == {manual: ("manual", False)}


async def test_empty_scope_does_nothing(world: _World) -> None:
    category = await world.category()
    await world.person(category)
    job = await world.job(category)

    assert await _sync(job_ids=[]) == {"added": 0, "removed": 0}
    assert await _sync(category_ids=[]) == {"added": 0, "removed": 0}
    assert await _rows(job) == {}


async def test_category_panel_changes_reach_open_jobs(
    world: _World, app_client, app_auth_headers
) -> None:
    """Panel „Kategorie kompetencji”: dopisanie osoby do kategorii i zdjęcie
    jej zmieniają uczestników otwartych rekrutacji w tej samej transakcji."""
    category = await world.category()
    person = await world.person(None)
    job = await world.job(category)
    closed = await world.job(category, status=JobStatus.closed)

    put = await app_client.put(
        "/api/competence-team/assignments",
        json={"user_id": person, "competence_category_id": category, "priority": 2},
        headers=app_auth_headers,
    )
    assert put.status_code == 200, put.text
    assert await _rows(job) == {person: ("auto_cc", False)}
    assert await _rows(closed) == {}

    async with AsyncSessionLocal() as db:
        assignment_id = await db.scalar(
            select(UserCompetenceCategory.id).where(
                UserCompetenceCategory.user_id == person,
                UserCompetenceCategory.competence_category_id == category,
            )
        )
    removed = await app_client.delete(
        f"/api/competence-team/assignments/{assignment_id}", headers=app_auth_headers
    )
    assert removed.status_code == 200, removed.text
    assert await _rows(job) == {}
