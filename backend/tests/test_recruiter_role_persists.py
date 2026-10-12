"""Rola „Rekruter” nie zależy od miejsca, w którym osobę dopisano (12.10.2026).

Zgłoszenie Head of Recruitment: przy rekrutacji jest kilka osób, a filtr
„Rekruter” i wiersz listy pokazują tylko tę główną. Filtr liczył wszystkich,
ale dwie drogi dopisania osoby miały różne skutki: osoba dodana z pulpitu
znikała, gdy request wychodził z „Szukamy” (automat zwalnia przypisania),
a osoba dopisana w panelu „Zespół” nie dostawała dzwonka.

Strażnik: niezależnie od drogi (pulpit, panel, zmiana prowadzącego) filtr
``GET /api/jobs?worked_by=`` zwraca rekrutację, wiersz niesie osobę w polu
``recruiters``, osoba ma dzwonek — także po wyjściu requestu z puli.

Baza testowa jest wspólna i nieczyszczona: każdy test zakłada własne osoby
i rekrutacje i pyta filtr o swoją osobę.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.job_work_assignment import JobWorkAssignment
from app.models.user import UserRole
from tests.test_audit_r7_jobs import _ids, _seed_user
from tests.test_audit_r7_jobs import _seed_job as _seed_published_job
from tests.test_jobs_ownership import _assignment_bells, _drop_jobs, _login
from tests.test_jobs_ownership import _seed_job as _seed_draft_job
from tests.test_jobs_ownership import _seed_user as _seed_login_user

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"),
]


# ── Pomocnicy ────────────────────────────────────────────────────────────────

_SEEDED: list[int] = []


@pytest_asyncio.fixture(autouse=True)
async def _drop_seeded_jobs():
    """Request zostawiony w puli dostawałby ludzi od automatu z innych plików."""
    _SEEDED.clear()
    yield
    if _SEEDED:
        await _drop_jobs(list(_SEEDED))


async def _seed_job(token: str, **fields) -> int:
    job_id = await _seed_published_job(token, **fields)
    _SEEDED.append(job_id)
    return job_id


async def _board_add(
    client: AsyncClient, headers: dict, job_id: int, user_id: int
) -> None:
    added = await client.post(
        f"/api/request-board/jobs/{job_id}/people",
        json={"user_id": user_id, "role": "recruiter"},
        headers=headers,
    )
    assert added.status_code == 200, added.text


async def _panel_add(client: AsyncClient, headers: dict, job_id: int, user_id: int):
    return await client.post(
        f"/api/jobs/{job_id}/collaborators",
        json={"user_id": user_id},
        headers=headers,
    )


async def _member_source(job_id: int, user_id: int) -> Optional[str]:
    """Źródło trwałego wpisu osoby w zespole; ``None`` = wpisu nie ma."""
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobCollaborator).where(
                JobCollaborator.job_id == job_id,
                JobCollaborator.user_id == user_id,
            )
        )
    if row is None or row.removed_from_auto_cc:
        return None
    return row.source.value


async def _assignment_rows(job_id: int, user_id: int) -> list[tuple[str, str | None]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(JobWorkAssignment.state, JobWorkAssignment.release_reason)
                .where(
                    JobWorkAssignment.job_id == job_id,
                    JobWorkAssignment.user_id == user_id,
                )
                .order_by(JobWorkAssignment.id)
            )
        ).all()
    return [(state, reason) for state, reason in rows]


async def _recruiters(
    client: AsyncClient, headers: dict, job_id: int, user_id: int
) -> list[tuple[int, str]]:
    """Osoby z wiersza listy przefiltrowanej po ``user_id`` — (id, skąd)."""
    response = await client.get(
        f"/api/jobs?page_size=100&worked_by={user_id}", headers=headers
    )
    assert response.status_code == 200, response.text
    rows = {row["id"]: row for row in response.json()["items"]}
    assert job_id in rows, f"filtr „Rekruter” nie zwrócił rekrutacji {job_id}"
    return [
        (person["user_id"], person["via"])
        for person in rows[job_id]["recruiters"]
        if not person["proposed"]
    ]


async def _leave_pool(job_id: int, exit_state: str) -> None:
    """Request wychodzi z „Szukamy”, a automat zwalnia jego przypisania.

    Zwolnienie wprost, z powodem, który wpisałby planer (``out_of_pool``) —
    prawdziwy przebieg ma osobny test, bo rusza requesty całej wspólnej bazy.
    """
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if exit_state == "champion":
            job.champion_found_at = now
        elif exit_state == "finished":
            job.status = JobStatus.closed
            job.work_state = "finished"
        else:
            job.work_state = exit_state
        job.work_state_changed_at = now
        await db.execute(
            update(JobWorkAssignment)
            .where(
                JobWorkAssignment.job_id == job_id,
                JobWorkAssignment.state != "released",
            )
            .values(state="released", released_at=now, release_reason=exit_state)
        )
        await db.commit()


# ── Pulpit „Requesty i obłożenie” ────────────────────────────────────────────


@pytest.mark.parametrize(
    "exit_state", ["champion", "client_silent", "to_review", "finished"]
)
async def test_person_added_from_the_board_stays_after_the_request_leaves_the_pool(
    app_client: AsyncClient, app_auth_headers: dict, exit_state: str
) -> None:
    first = await _seed_user()
    second = await _seed_user()
    third = await _seed_user()
    job_id = await _seed_job("RoleStays", work_state="searching")
    for person in (first, second, third):
        await _board_add(app_client, app_auth_headers, job_id, person)

    # Pierwsza osoba została prowadzącym — jest przy rekrutacji z urzędu.
    assert await _member_source(job_id, first) is None
    assert await _member_source(job_id, second) == "manual"
    assert await _member_source(job_id, third) == "manual"
    for person in (second, third):
        assert await _assignment_bells(person, job_id) == 1
        assert await _recruiters(app_client, app_auth_headers, job_id, person) == [
            (first, "owner"),
            (second, "assignment"),
            (third, "assignment"),
        ]

    await _leave_pool(job_id, exit_state)

    # Przypisania zeszły z obłożenia, a osoby zostały Rekruterami rekrutacji.
    for person in (first, second, third):
        assert await _assignment_rows(job_id, person) == [("released", exit_state)]
        assert await _ids(app_client, app_auth_headers, f"worked_by={person}") == {
            job_id
        }
    assert await _recruiters(app_client, app_auth_headers, job_id, third) == [
        (first, "owner"),
        (second, "collaborator"),
        (third, "collaborator"),
    ]


async def test_planner_pass_releases_the_assignment_but_not_the_role(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
) -> None:
    """Prawdziwy przebieg automatu po „Mamy championa” — w wycofanej transakcji."""
    from app.services.job_team import (
        jobs_worked_by_clause,
        recruiters_for_jobs,
        working,
    )
    from app.services.recruitment_allocation import allocation_lock
    from app.services.request_allocation import run_request_allocation

    monkeypatch.setattr(settings, "COMPASS_AVAILABILITY_ENABLED", False)
    first = await _seed_user()
    second = await _seed_user()
    job_id = await _seed_job("RolePlanner", work_state="searching")
    for person in (first, second):
        await _board_add(app_client, app_auth_headers, job_id, person)
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(settings.BUSINESS_TZ)).date().isoformat()

    async with AsyncSessionLocal() as db:
        try:
            await allocation_lock(db)
            job = await db.get(Job, job_id)
            job.champion_found_at = now
            await db.flush()
            await run_request_allocation(
                db,
                mode="shadow",
                availability_fresh=False,
                available_ids=set(),
                stats={"last_review_date": today},
                now=now,
            )
            live = (
                await db.scalars(
                    select(JobWorkAssignment.user_id).where(
                        JobWorkAssignment.job_id == job_id,
                        JobWorkAssignment.state != "released",
                    )
                )
            ).all()
            assert live == []
            team = await recruiters_for_jobs(db, [job_id])
            assert {p.user_id: p.via for p in working(team[job_id])} == {
                first: "owner",
                second: "collaborator",
            }
            listed = (
                await db.scalars(
                    select(Job.id).where(
                        Job.id == job_id, jobs_worked_by_clause([second])
                    )
                )
            ).all()
            assert listed == [job_id]
        finally:
            await db.rollback()


async def test_board_add_promotes_a_category_row_instead_of_failing(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Rekruter z kategorii rekrutacji ma już wiersz ``auto_cc`` — także zdjęty."""
    first = await _seed_user()
    from_category = await _seed_user()
    removed_earlier = await _seed_user()
    job_id = await _seed_job("RolePromote", work_state="searching")
    await _board_add(app_client, app_auth_headers, job_id, first)
    async with AsyncSessionLocal() as db:
        db.add(
            JobCollaborator(
                job_id=job_id,
                user_id=from_category,
                source=JobCollaboratorSource.auto_cc,
            )
        )
        db.add(
            JobCollaborator(
                job_id=job_id,
                user_id=removed_earlier,
                source=JobCollaboratorSource.auto_cc,
                removed_from_auto_cc=True,
                removed_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    for person in (from_category, removed_earlier):
        await _board_add(app_client, app_auth_headers, job_id, person)
        assert await _member_source(job_id, person) == "manual"


# ── Panel „Zespół” i okno edycji (``/collaborators``) ────────────────────────


async def test_panel_add_rings_the_person_once_and_the_filter_finds_them(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    owner = await _seed_user()
    person = await _seed_user()
    job_id = await _seed_job("RolePanel", work_state="to_review", recruiter_id=owner)

    for _ in range(2):
        added = await _panel_add(app_client, app_auth_headers, job_id, person)
        assert added.status_code == 201, added.text

    # Do 12.10.2026 dopisanie z panelu nie mówiło osobie nic.
    assert await _assignment_bells(person, job_id) == 1
    assert await _assignment_bells(owner, job_id) == 0
    assert await _recruiters(app_client, app_auth_headers, job_id, person) == [
        (owner, "owner"),
        (person, "collaborator"),
    ]


async def test_joining_a_recruitment_yourself_rings_no_bell(
    app_client: AsyncClient,
) -> None:
    owner = await _seed_user()
    me, email, password = await _seed_login_user(UserRole.recruiter)
    job_id = await _seed_draft_job(recruiter_id=owner)
    headers = await _login(app_client, email, password)

    joined = await _panel_add(app_client, headers, job_id, me)

    assert joined.status_code == 201, joined.text
    assert await _member_source(job_id, me) == "manual"
    assert await _assignment_bells(me, job_id) == 0


async def test_panel_add_of_a_person_already_on_the_board_rings_no_second_bell(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    first = await _seed_user()
    second = await _seed_user()
    job_id = await _seed_job("RoleTwice", work_state="searching")
    for person in (first, second):
        await _board_add(app_client, app_auth_headers, job_id, person)

    again = await _panel_add(app_client, app_auth_headers, job_id, second)

    assert again.status_code == 201, again.text
    assert await _assignment_bells(second, job_id) == 1


async def test_removing_a_board_person_through_the_collaborators_route(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Okno edycji zdejmuje „kolejne osoby” tą trasą. Osoba z pulpitu ma też
    aktywne przypisanie — samo skasowanie wpisu zostawiłoby ją Rekruterem."""
    first = await _seed_user()
    second = await _seed_user()
    _, email, password = await _seed_login_user(UserRole.recruiter)
    job_id = await _seed_job("RoleRemove", work_state="searching")
    for person in (first, second):
        await _board_add(app_client, app_auth_headers, job_id, person)

    # Redaktor bez prawa do obsady nie zdejmuje osoby przypisanej z pulpitu.
    editor = await _login(app_client, email, password)
    denied = await app_client.delete(
        f"/api/jobs/{job_id}/collaborators/{second}", headers=editor
    )
    assert denied.status_code == 409, denied.text
    assert "Head of Recruitment" in denied.json()["detail"]
    assert await _ids(app_client, app_auth_headers, f"worked_by={second}") == {job_id}

    removed = await app_client.delete(
        f"/api/jobs/{job_id}/collaborators/{second}", headers=app_auth_headers
    )
    assert removed.status_code == 204, removed.text
    assert await _member_source(job_id, second) is None
    assert await _assignment_rows(job_id, second) == [("released", "manual")]
    assert await _ids(app_client, app_auth_headers, f"worked_by={second}") == set()
    # Prowadzący zostaje nietknięty.
    assert await _ids(app_client, app_auth_headers, f"worked_by={first}") == {job_id}


# ── Zmiana prowadzącego ──────────────────────────────────────────────────────


async def test_replaced_owner_loses_the_role_even_with_a_member_row(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """„Zmień” zastępuje osobę, nie dokłada drugiej — także gdy zastępowana
    była wcześniej kolejną osobą i ma trwały wpis w zespole."""
    first = await _seed_user()
    second = await _seed_user()
    third = await _seed_user()
    bystander = await _seed_user()
    job_id = await _seed_job("RoleReplace", work_state="searching")
    for person in (first, second, bystander):
        await _board_add(app_client, app_auth_headers, job_id, person)

    for new_owner in (second, third):
        changed = await app_client.post(
            f"/api/jobs/{job_id}/owner",
            json={"user_id": new_owner},
            headers=app_auth_headers,
        )
        assert changed.status_code == 200, changed.text

    assert await _member_source(job_id, second) is None
    for replaced in (first, second):
        assert (
            await _ids(app_client, app_auth_headers, f"worked_by={replaced}") == set()
        )
    # Osoba, której nikt nie zastępował, zostaje przy rekrutacji.
    assert await _recruiters(app_client, app_auth_headers, job_id, bystander) == [
        (third, "owner"),
        (bystander, "assignment"),
    ]
