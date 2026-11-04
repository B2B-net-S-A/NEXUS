"""„Poprzedni rekruter” — zejście z P1 i zamknięcie usypia zespół (14.10.2026).

Prośba Head of Recruitment: przy zamknięciu albo zejściu z P1 wszyscy, którzy
pracowali jako „Rekruter”, przechodzą do „Poprzedni rekruter”; powrót na P1
albo ponowne otwarcie przy P1 przywraca ich samo. Nic nie jest kasowane —
``jobs.recruiter_id`` i ręcznie dopisani zostają, reguła zespołu pomija osoby
z otwartym wierszem ``job_previous_recruiters``.

Baza testowa jest wspólna i nieczyszczona: każdy test zakłada własne osoby
i rekrutacje i pyta o swoje.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fastapi import BackgroundTasks
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobPriority, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.job_previous_recruiter import JobPreviousRecruiter
from app.models.job_work_assignment import JobWorkAssignment
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from tests.test_audit_r7_jobs import _ids, _seed_user
from tests.test_audit_r7_jobs import _seed_job as _seed_published_job
from tests.test_jobs_ownership import _drop_jobs, _login
from tests.test_jobs_ownership import _seed_user as _seed_login_user

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"),
]

_SEEDED: list[int] = []


@pytest_asyncio.fixture(autouse=True)
async def _drop_seeded_jobs():
    """Request zostawiony w puli dostawałby ludzi od automatu z innych plików."""
    _SEEDED.clear()
    yield
    if _SEEDED:
        await _drop_jobs(list(_SEEDED))


# ── Pomocnicy ────────────────────────────────────────────────────────────────


async def _team_job(
    priority: JobPriority = JobPriority.urgent,
) -> tuple[int, int, int, int]:
    """Rekrutacja P1 w „Szukamy” z trzema drogami do zespołu: prowadzący,
    ręcznie dopisany współpracownik i osoba tylko z przypisaniem automatu."""
    owner = await _seed_user()
    collaborator = await _seed_user()
    assignee = await _seed_user()
    job_id = await _seed_published_job(
        "PrevRec",
        work_state="searching",
        recruiter_id=owner,
        priority=priority,
        is_open=True,
    )
    _SEEDED.append(job_id)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            JobCollaborator(
                job_id=job_id,
                user_id=collaborator,
                source=JobCollaboratorSource.manual,
            )
        )
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=assignee,
                role="recruiter",
                source="auto",
                state="active",
                assigned_at=now,
            )
        )
        await db.commit()
    return job_id, owner, collaborator, assignee


async def _job(client: AsyncClient, headers: dict, job_id: int) -> dict:
    response = await client.get(f"/api/jobs/{job_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _working(payload: dict) -> set[int]:
    return {p["user_id"] for p in payload["recruiters"] if not p["proposed"]}


def _previous(payload: dict) -> dict[int, str]:
    return {p["user_id"]: p["reason"] for p in payload["previous_recruiters"]}


async def _set_priority(
    client: AsyncClient, headers: dict, job_id: int, priority: str
) -> None:
    response = await client.patch(
        f"/api/jobs/{job_id}", json={"priority": priority}, headers=headers
    )
    assert response.status_code == 200, response.text


async def _bells(user_id: int, job_id: int, ntype: NotificationType) -> int:
    async with AsyncSessionLocal() as db:
        return int(
            await db.scalar(
                select(func.count(Notification.id)).where(
                    Notification.user_id == user_id,
                    Notification.notification_type == ntype,
                    Notification.related_entity_type == "job",
                    Notification.related_entity_id == job_id,
                )
            )
            or 0
        )


async def _open_rows(job_id: int) -> dict[int, JobPreviousRecruiter]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(JobPreviousRecruiter).where(
                    JobPreviousRecruiter.job_id == job_id,
                    JobPreviousRecruiter.cleared_at.is_(None),
                )
            )
        ).all()
    return {row.user_id: row for row in rows}


async def _cleared_reason(job_id: int, user_id: int) -> str | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(JobPreviousRecruiter.cleared_reason)
            .where(
                JobPreviousRecruiter.job_id == job_id,
                JobPreviousRecruiter.user_id == user_id,
            )
            .order_by(JobPreviousRecruiter.id.desc())
            .limit(1)
        )


# ── Zejście z P1 i powrót ────────────────────────────────────────────────────


async def test_leaving_p1_parks_the_team_and_returning_brings_it_back(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id, owner, collaborator, assignee = await _team_job()
    team = {owner, collaborator, assignee}
    assert _working(await _job(app_client, app_auth_headers, job_id)) == team

    await _set_priority(app_client, app_auth_headers, job_id, "medium")

    payload = await _job(app_client, app_auth_headers, job_id)
    assert _working(payload) == set()
    assert _previous(payload) == {uid: "priority" for uid in team}
    # Nic nie zostało skasowane: prowadzący i ręczny wpis są na miejscu.
    assert payload["recruiter_id"] == owner
    async with AsyncSessionLocal() as db:
        reasons = (
            await db.scalars(
                select(JobWorkAssignment.release_reason).where(
                    JobWorkAssignment.job_id == job_id,
                    JobWorkAssignment.user_id == assignee,
                )
            )
        ).all()
    assert reasons == ["parked"]
    for person in team:
        assert await _bells(person, job_id, NotificationType.recruiter_parked) == 1
        # „Moje” i filtr „Rekruter” na otwartych go nie znają…
        assert job_id not in await _ids(
            app_client, app_auth_headers, f"worked_by={person}&open_only=true"
        )
        # …a zakres „Wszystkie” tak.
        assert job_id in await _ids(app_client, app_auth_headers, f"worked_by={person}")
    assert job_id in await _ids(
        app_client, app_auth_headers, "nobody_working=true&open_only=true"
    )

    await _set_priority(app_client, app_auth_headers, job_id, "urgent")

    payload = await _job(app_client, app_auth_headers, job_id)
    assert _working(payload) == team
    assert _previous(payload) == {}
    for person in team:
        assert await _bells(person, job_id, NotificationType.recruiter_restored) == 1
        assert await _cleared_reason(job_id, person) == "restored"
    # Osoba automatu wraca jako przypisanie automatu (planer zwolni je za urlop).
    async with AsyncSessionLocal() as db:
        live = await db.scalar(
            select(JobWorkAssignment.source).where(
                JobWorkAssignment.job_id == job_id,
                JobWorkAssignment.user_id == assignee,
                JobWorkAssignment.state == "active",
            )
        )
    assert live == "auto"


async def test_p2_and_accepting_switch_does_not_touch_the_team(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id, owner, collaborator, assignee = await _team_job(JobPriority.medium)

    await _set_priority(app_client, app_auth_headers, job_id, "low")
    await _set_priority(app_client, app_auth_headers, job_id, "medium")

    payload = await _job(app_client, app_auth_headers, job_id)
    assert _working(payload) == {owner, collaborator, assignee}
    assert await _open_rows(job_id) == {}


async def test_person_added_while_not_p1_works_and_stays_after_return(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id, owner, collaborator, assignee = await _team_job()
    await _set_priority(app_client, app_auth_headers, job_id, "medium")
    newcomer = await _seed_user()

    added = await app_client.post(
        f"/api/jobs/{job_id}/collaborators",
        json={"user_id": newcomer},
        headers=app_auth_headers,
    )
    assert added.status_code == 201, added.text
    assert _working(await _job(app_client, app_auth_headers, job_id)) == {newcomer}

    await _set_priority(app_client, app_auth_headers, job_id, "urgent")
    assert _working(await _job(app_client, app_auth_headers, job_id)) == {
        owner,
        collaborator,
        assignee,
        newcomer,
    }


async def test_readding_a_previous_recruiter_brings_only_that_person_back(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id, owner, collaborator, assignee = await _team_job()
    await _set_priority(app_client, app_auth_headers, job_id, "medium")

    # Prowadzący dodany przez człowieka — zamiast 409 „już prowadzi”.
    added = await app_client.post(
        f"/api/jobs/{job_id}/collaborators",
        json={"user_id": owner},
        headers=app_auth_headers,
    )
    assert added.status_code == 201, added.text

    payload = await _job(app_client, app_auth_headers, job_id)
    assert _working(payload) == {owner}
    assert set(_previous(payload)) == {collaborator, assignee}
    assert await _cleared_reason(job_id, owner) == "readded"


async def test_dismissed_previous_recruiter_does_not_come_back(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id, owner, collaborator, assignee = await _team_job()
    await _set_priority(app_client, app_auth_headers, job_id, "medium")

    dismissed = await app_client.delete(
        f"/api/jobs/{job_id}/previous-recruiters/{collaborator}",
        headers=app_auth_headers,
    )
    assert dismissed.status_code == 204, dismissed.text
    again = await app_client.delete(
        f"/api/jobs/{job_id}/previous-recruiters/{collaborator}",
        headers=app_auth_headers,
    )
    assert again.status_code == 404, again.text

    # Usunięty z poprzednich nie pracuje też przy P2 — schodzi z zespołu.
    payload = await _job(app_client, app_auth_headers, job_id)
    assert collaborator not in _working(payload)
    assert collaborator not in _previous(payload)

    await _set_priority(app_client, app_auth_headers, job_id, "urgent")
    assert _working(await _job(app_client, app_auth_headers, job_id)) == {
        owner,
        assignee,
    }
    assert await _cleared_reason(job_id, collaborator) == "dismissed"


async def test_dismissed_owner_leaves_the_recruiter_field(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id, owner, collaborator, assignee = await _team_job()
    await _set_priority(app_client, app_auth_headers, job_id, "medium")

    dismissed = await app_client.delete(
        f"/api/jobs/{job_id}/previous-recruiters/{owner}", headers=app_auth_headers
    )
    assert dismissed.status_code == 204, dismissed.text

    payload = await _job(app_client, app_auth_headers, job_id)
    assert payload["recruiter_id"] is None
    assert _working(payload) == set()
    assert set(_previous(payload)) == {collaborator, assignee}
    await _set_priority(app_client, app_auth_headers, job_id, "urgent")
    assert _working(await _job(app_client, app_auth_headers, job_id)) == {
        collaborator,
        assignee,
    }


async def test_owner_without_the_recruiter_role_does_not_come_back_as_recruiter(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Rekruterem jest tylko rola rekrutera — prowadzący, który ją stracił
    (np. DL z Traffita), przy powrocie na P1 schodzi z pola „Rekruter”."""
    job_id, owner, collaborator, assignee = await _team_job()
    await _set_priority(app_client, app_auth_headers, job_id, "medium")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User)
            .where(User.id.in_([owner, collaborator]))
            .values(role=UserRole.delivery_lead, roles=["delivery_lead"])
        )
        await db.commit()

    await _set_priority(app_client, app_auth_headers, job_id, "urgent")

    payload = await _job(app_client, app_auth_headers, job_id)
    assert _working(payload) == {assignee}
    assert payload["recruiter_id"] is None
    assert _previous(payload) == {}


async def test_picking_the_parked_owner_in_the_edit_window_brings_them_back(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id, owner, _collaborator, _assignee = await _team_job()
    await _set_priority(app_client, app_auth_headers, job_id, "medium")

    saved = await app_client.patch(
        f"/api/jobs/{job_id}", json={"recruiter_id": owner}, headers=app_auth_headers
    )
    assert saved.status_code == 200, saved.text

    payload = await _job(app_client, app_auth_headers, job_id)
    assert owner in _working(payload)
    assert owner not in _previous(payload)
    assert await _cleared_reason(job_id, owner) == "readded"


async def test_dismissing_needs_the_right_to_staff_the_job(
    app_client: AsyncClient,
) -> None:
    job_id, _owner, collaborator, _assignee = await _team_job()
    _uid, email, password = await _seed_login_user(UserRole.recruiter, "prev")
    headers = await _login(app_client, email, password)

    response = await app_client.delete(
        f"/api/jobs/{job_id}/previous-recruiters/{collaborator}", headers=headers
    )
    assert response.status_code == 403, response.text


async def test_inactive_and_role_less_people_stay_out_on_return(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id, owner, collaborator, assignee = await _team_job()
    await _set_priority(app_client, app_auth_headers, job_id, "medium")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(User).where(User.id == collaborator).values(is_active=False)
        )
        await db.execute(
            update(User)
            .where(User.id == assignee)
            .values(role=UserRole.delivery_lead, roles=["delivery_lead"])
        )
        await db.commit()

    await _set_priority(app_client, app_auth_headers, job_id, "urgent")

    assert _working(await _job(app_client, app_auth_headers, job_id)) == {owner}
    assert await _cleared_reason(job_id, collaborator) == "skipped"
    assert await _cleared_reason(job_id, assignee) == "skipped"
    assert await _bells(assignee, job_id, NotificationType.recruiter_restored) == 0


async def test_parked_owner_can_claim_the_job_back(app_client: AsyncClient) -> None:
    owner, email, password = await _seed_login_user(UserRole.recruiter, "prevclaim")
    # `is_open=False`: przejęcie bez planu priorytetów — wiersz zapotrzebowania
    # blokowałby sprzątanie rekrutacji po teście.
    job_id = await _seed_published_job(
        "PrevClaim",
        work_state="searching",
        recruiter_id=owner,
        priority=JobPriority.urgent,
        is_open=False,
    )
    _SEEDED.append(job_id)
    from app.services.job_previous_recruiters import park_team

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        await park_team(
            db,
            job,
            reason="priority",
            actor_id=None,
            notify=False,
            release_assignments=True,
        )
        job.priority = JobPriority.medium
        await db.commit()

    headers = await _login(app_client, email, password)
    claimed = await app_client.post(f"/api/jobs/{job_id}/claim", headers=headers)
    assert claimed.status_code == 200, claimed.text
    assert owner in _working(claimed.json())
    assert await _cleared_reason(job_id, owner) == "readded"


# ── Zamknięcie i ponowne otwarcie ────────────────────────────────────────────


async def test_closing_parks_the_team_quietly_and_keeps_history(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id, owner, collaborator, assignee = await _team_job()

    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "competitor", "acknowledge_active_cards": True},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text

    payload = await _job(app_client, app_auth_headers, job_id)
    assert _working(payload) == set()
    assert _previous(payload) == {
        owner: "closed",
        collaborator: "closed",
        assignee: "closed",
    }
    assert payload["recruiter_id"] == owner
    for person in (owner, collaborator, assignee):
        assert await _bells(person, job_id, NotificationType.recruiter_parked) == 0
        assert job_id in await _ids(app_client, app_auth_headers, f"worked_by={person}")
    # Zmiana priorytetu zamkniętej rekrutacji niczego nie przywraca.
    await _set_priority(app_client, app_auth_headers, job_id, "medium")
    await _set_priority(app_client, app_auth_headers, job_id, "urgent")
    assert _working(await _job(app_client, app_auth_headers, job_id)) == set()


async def test_owner_removed_before_closing_is_not_parked() -> None:
    """Ręczne zdjęcie liczy się od zmiany stanu — zespół liczony PRZED nią."""
    from app.services.job_lifecycle import PostCommit, close_job_core
    from app.models.job import JobCloseReason

    owner = await _seed_user()
    job_id = await _seed_published_job(
        "PrevManual",
        work_state="searching",
        recruiter_id=owner,
        priority=JobPriority.urgent,
        is_open=True,
        work_state_changed_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    _SEEDED.append(job_id)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=owner,
                role="recruiter",
                source="owner",
                state="released",
                assigned_at=now,
                released_at=now,
                release_reason="manual",
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        try:
            job = await db.get(Job, job_id)
            await close_job_core(
                db,
                job,
                reason=JobCloseReason.other,
                notes=None,
                actor_id=None,
                effects=PostCommit(BackgroundTasks()),
            )
            await db.flush()
            parked = (
                await db.scalars(
                    select(JobPreviousRecruiter.user_id).where(
                        JobPreviousRecruiter.job_id == job_id
                    )
                )
            ).all()
            assert parked == []
        finally:
            await db.rollback()


@pytest.mark.parametrize("priority", [JobPriority.urgent, JobPriority.medium])
async def test_reopening_restores_the_team_only_at_p1(
    app_client: AsyncClient, app_auth_headers: dict, priority: JobPriority
) -> None:
    from app.services.job_lifecycle import PostCommit, reopen_keep_team_core

    job_id, owner, collaborator, assignee = await _team_job()
    closed = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "competitor", "acknowledge_active_cards": True},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text

    async with AsyncSessionLocal() as db:
        try:
            actor = await db.scalar(
                select(User).where(User.role == UserRole.admin).limit(1)
            )
            job = await db.get(Job, job_id)
            job.status = JobStatus.published
            job.priority = priority
            await db.flush()
            await reopen_keep_team_core(db, job, actor, PostCommit(BackgroundTasks()))
            await db.flush()
            from app.services.job_team import recruiters_for_jobs, working

            team = {
                p.user_id
                for p in working((await recruiters_for_jobs(db, [job_id]))[job_id])
            }
            owner_rows = (
                await db.scalars(
                    select(JobWorkAssignment.source).where(
                        JobWorkAssignment.job_id == job_id,
                        JobWorkAssignment.user_id == owner,
                        JobWorkAssignment.state == "active",
                    )
                )
            ).all()
            owner_bells = await db.scalar(
                select(func.count(Notification.id)).where(
                    Notification.user_id == owner,
                    Notification.related_entity_type == "job",
                    Notification.related_entity_id == job_id,
                    Notification.notification_type.in_(
                        [
                            NotificationType.request_assignment_changed,
                            NotificationType.recruiter_restored,
                        ]
                    ),
                )
            )
            collaborator_bells = await db.scalar(
                select(func.count(Notification.id)).where(
                    Notification.user_id == collaborator,
                    Notification.notification_type
                    == NotificationType.recruiter_restored,
                    Notification.related_entity_id == job_id,
                )
            )
            if priority == JobPriority.urgent:
                assert team == {owner, collaborator, assignee}
                assert owner_rows == ["manual"]
                # Prowadzący: jeden dzwonek „request wrócił”, bez dubla.
                assert owner_bells == 1
                assert collaborator_bells == 1
            else:
                assert team == set()
                assert owner_rows == []
                assert owner_bells == 0
        finally:
            await db.rollback()


# ── Automat ──────────────────────────────────────────────────────────────────


async def test_automat_does_not_adopt_a_parked_owner(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.services.request_allocation import _adopt_owners

    job_id, owner, _collaborator, _assignee = await _team_job()
    await _set_priority(app_client, app_auth_headers, job_id, "medium")

    async with AsyncSessionLocal() as db:
        try:
            await _adopt_owners(db, blocked=frozenset(), now=datetime.now(timezone.utc))
            live = await db.scalar(
                select(func.count(JobWorkAssignment.id)).where(
                    JobWorkAssignment.job_id == job_id,
                    JobWorkAssignment.user_id == owner,
                    JobWorkAssignment.state != "released",
                )
            )
            assert live == 0
        finally:
            await db.rollback()


async def test_job_bells_skip_a_parked_owner(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.services.job_membership import is_member_of_job, list_job_member_ids
    from app.services.job_previous_recruiters import working_owner_id

    job_id, owner, collaborator, _assignee = await _team_job()
    await _set_priority(app_client, app_auth_headers, job_id, "medium")

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert await working_owner_id(db, job) is None
        bell_ids = await list_job_member_ids(db, job_id, include_parked=False)
        assert owner not in bell_ids and collaborator not in bell_ids
        # Dostęp i czat znają ją jak dotąd.
        assert owner in await list_job_member_ids(db, job_id)
        person = await db.get(User, collaborator)
        assert await is_member_of_job(db, person, job_id)
