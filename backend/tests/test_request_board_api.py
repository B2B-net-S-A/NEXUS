"""Trasy automatu przydziału (0371): porządek w requestach, panel kategorii, pulpit.

Baza testowa jest wspólna i nieczyszczona — każdy test zakłada własne
rekrutacje i osoby i asertuje wyłącznie po nich.
"""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"),
]


async def _seed_job(*, work_state: str = "to_review", champion: bool = False) -> int:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.competence_category import CompetenceCategory
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"rb-client-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        qa = await db.scalar(
            select(CompetenceCategory.id).where(
                CompetenceCategory.slug == "security_quality"
            )
        )
        job = Job(
            title=f"Tester RB {uuid.uuid4().hex[:6]}",
            client_id=client.id,
            status=JobStatus.published,
            work_state=work_state,
            competence_category_id=qa,
            champion_found_at=datetime.now(timezone.utc) if champion else None,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _seed_recruiter() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        marker = uuid.uuid4().hex[:10]
        user = User(
            email=f"rb-{marker}@example.com",
            name=f"Rekruter RB {marker}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def test_review_tab_lists_the_job_and_patch_moves_it_to_searching(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id = await _seed_job()
    resp = await app_client.get(
        "/api/request-work-states",
        params={"tab": "to_review"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    assert job_id in {row["job_id"] for row in resp.json()["rows"]}

    patch = await app_client.patch(
        "/api/request-work-states",
        json={"changes": [{"job_id": job_id, "state": "searching"}]},
        headers=app_auth_headers,
    )
    assert patch.status_code == 200
    assert patch.json()["changed"] == [job_id]

    again = await app_client.get(
        "/api/request-work-states",
        params={"tab": "searching"},
        headers=app_auth_headers,
    )
    assert job_id in {row["job_id"] for row in again.json()["rows"]}


async def test_unknown_state_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id = await _seed_job()
    resp = await app_client.patch(
        "/api/request-work-states",
        json={"changes": [{"job_id": job_id, "state": "champion"}]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


async def test_board_shows_manual_person_and_champion_is_not_load(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    searching = await _seed_job(work_state="searching")
    champion = await _seed_job(work_state="searching")
    person = await _seed_recruiter()
    for job_id in (searching, champion):
        added = await app_client.post(
            f"/api/request-board/jobs/{job_id}/people",
            json={"user_id": person, "role": "recruiter"},
            headers=app_auth_headers,
        )
        assert added.status_code == 200, added.text
    # Champion pojawia się po przypisaniu — osoba zostaje, ale to nie obłożenie.
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, champion)
        job.champion_found_at = datetime.now(timezone.utc)
        await db.commit()

    board = (
        await app_client.get("/api/request-board", headers=app_auth_headers)
    ).json()
    rows = {r["job_id"]: r for r in board["requests"]}
    assert rows[searching]["champion"] is False
    assert rows[champion]["champion"] is True
    assert [p["user_id"] for p in rows[searching]["people"]] == [person]
    # Pierwszy rekruter dodany z pulpitu zostaje prowadzącym rekrutacji.
    assert rows[searching]["people"][0]["via"] == "owner"
    assert rows[searching]["people"][0]["proposed"] is False
    assert rows[searching]["priority_level"] == "p2"
    assert rows[searching]["delivery_lead"] is None
    assert rows[searching]["opened_effective_at"] is not None
    load = {p["user_id"]: p for p in board["load"]}
    assert load[person]["count"] == 1
    assert load[person]["proposed"] == 0
    assert [r["job_id"] for r in load[person]["requests"]] == [searching]

    removed = await app_client.delete(
        f"/api/request-board/jobs/{searching}/people/{person}",
        headers=app_auth_headers,
    )
    assert removed.json() == {"removed": True}
    # Zdjęcie z pulpitu zdejmuje osobę ze wszystkich miejsc naraz — także
    # z roli prowadzącego (do 02.10.2026 zostawała w `jobs.recruiter_id`).
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, searching)).recruiter_id is None
    board = (
        await app_client.get("/api/request-board", headers=app_auth_headers)
    ).json()
    rows = {r["job_id"]: r for r in board["requests"]}
    assert rows[searching]["people"] == []


async def test_board_shows_everyone_who_works_and_counts_proposals_apart(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Decyzja Artura 02.10.2026: nad requestem pracuje prowadzący, osoba
    z aktywnym przypisaniem albo ręcznie dopisany współpracownik. Do tej daty
    pulpit czytał same przypisania — prowadzący bez wiersza był niewidoczny,
    a propozycja automatu liczyła się jak praca."""
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobPriority
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
    from app.models.job_work_assignment import JobWorkAssignment
    from app.models.user import User, UserRole

    job_id = await _seed_job(work_state="searching")
    owner = await _seed_recruiter()
    collaborator = await _seed_recruiter()
    proposed = await _seed_recruiter()
    async with AsyncSessionLocal() as db:
        marker = uuid.uuid4().hex[:10]
        lead = User(
            email=f"rb-dl-{marker}@example.com",
            name=f"Delivery RB {marker}",
            role=UserRole.delivery_lead,
            roles=["delivery_lead"],
            is_active=True,
        )
        db.add(lead)
        await db.flush()
        job = await db.get(Job, job_id)
        job.recruiter_id = owner
        job.delivery_lead_id = lead.id
        job.priority = JobPriority.urgent
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
                user_id=proposed,
                role="sourcer",
                source="auto",
                state="proposed",
                assigned_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
        lead_id, lead_name = lead.id, lead.name

    board = (
        await app_client.get("/api/request-board", headers=app_auth_headers)
    ).json()
    row = next(r for r in board["requests"] if r["job_id"] == job_id)
    assert row["priority_level"] == "p1"
    assert row["delivery_lead"] == {"id": lead_id, "name": lead_name}
    assert [
        (p["user_id"], p["via"], p["proposed"], p["source"], p["role"])
        for p in row["people"]
    ] == [
        (owner, "owner", False, "owner", "recruiter"),
        (collaborator, "collaborator", False, "manual", "recruiter"),
        (proposed, "assignment", True, "auto", "sourcer"),
    ]
    load = {p["user_id"]: p for p in board["load"]}
    assert (load[owner]["count"], load[owner]["proposed"]) == (1, 0)
    assert (load[collaborator]["count"], load[collaborator]["proposed"]) == (1, 0)
    # Propozycja to jeszcze nie praca: w obłożeniu liczy się osobno.
    assert (load[proposed]["count"], load[proposed]["proposed"]) == (0, 1)
    assert [(r["job_id"], r["proposed"]) for r in load[proposed]["requests"]] == [
        (job_id, True)
    ]


async def test_delete_removes_owner_and_collaborator_and_rejects_a_proposal(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
    from app.models.job_work_assignment import JobWorkAssignment

    job_id = await _seed_job(work_state="searching")
    owner = await _seed_recruiter()
    collaborator = await _seed_recruiter()
    proposed = await _seed_recruiter()
    stranger = await _seed_recruiter()
    async with AsyncSessionLocal() as db:
        (await db.get(Job, job_id)).recruiter_id = owner
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
                user_id=proposed,
                role="recruiter",
                source="auto",
                state="proposed",
                assigned_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    async def remove(user_id: int):
        return await app_client.delete(
            f"/api/request-board/jobs/{job_id}/people/{user_id}",
            headers=app_auth_headers,
        )

    # Osoby spoza requestu nie ma czego zdejmować.
    assert (await remove(stranger)).json() == {"removed": False}
    assert (await remove(owner)).json() == {"removed": True}
    assert (await remove(collaborator)).json() == {"removed": True}
    # Propozycję odrzuca się — osoba nigdy nie pracowała nad requestem.
    assert (await remove(proposed)).json() == {"removed": True}
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).recruiter_id is None
        links = (
            await db.scalars(
                select(JobCollaborator).where(JobCollaborator.job_id == job_id)
            )
        ).all()
        assert list(links) == []
        rows = {
            row.user_id: (row.state, row.release_reason)
            for row in (
                await db.scalars(
                    select(JobWorkAssignment).where(JobWorkAssignment.job_id == job_id)
                )
            ).all()
        }
        assert rows == {
            proposed: ("released", "proposal:rejected"),
            # Prowadzący nie miał wiersza przypisania — zdjęcie zostawia ślad,
            # żeby automat nie zaproponował go do tego requestu ponownie.
            owner: ("released", "manual"),
        }

    # Zamknięta rekrutacja jest historią — prowadzący zostaje przy niej.
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.recruiter_id = owner
        job.status = JobStatus.closed
        await db.commit()
    closed = await remove(owner)
    assert closed.status_code == 409, closed.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).recruiter_id == owner


async def test_person_removed_and_added_again_is_the_working_owner_again(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Ponowne dodanie osoby z pulpitu znosi jej wcześniejsze ręczne zdjęcie.

    Bez tego osoba zdjęta i dodana ponownie w tym samym stanie requestu była
    prowadzącą, której reguła zespołu nie liczyła jako prowadzącej
    (``owner_is_working_clause``): panel proponował „Przypisz” zamiast „Dodaj
    osobę”, a kolejna osoba wchodziła na jej miejsce i zwalniała jej
    przypisanie."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.job_work_assignment import JobWorkAssignment
    from app.services.request_allocation import _blocked

    job_id = await _seed_job(work_state="searching")
    first = await _seed_recruiter()
    second = await _seed_recruiter()

    async def add(user_id: int):
        return await app_client.post(
            f"/api/request-board/jobs/{job_id}/people",
            json={"user_id": user_id, "role": "recruiter"},
            headers=app_auth_headers,
        )

    async def people() -> list[tuple[int, str]]:
        board = (
            await app_client.get("/api/request-board", headers=app_auth_headers)
        ).json()
        row = next(r for r in board["requests"] if r["job_id"] == job_id)
        return [(p["user_id"], p["via"]) for p in row["people"]]

    added = await add(first)
    assert added.status_code == 200, added.text
    assert await people() == [(first, "owner")]

    removed = await app_client.delete(
        f"/api/request-board/jobs/{job_id}/people/{first}",
        headers=app_auth_headers,
    )
    assert removed.json() == {"removed": True}
    assert await people() == []
    async with AsyncSessionLocal() as db:
        assert (job_id, first) in await _blocked(db)

    again = await add(first)
    assert again.status_code == 200, again.text
    assert await people() == [(first, "owner")]
    async with AsyncSessionLocal() as db:
        assert (job_id, first) not in await _blocked(db)
        reasons = (
            await db.scalars(
                select(JobWorkAssignment.release_reason).where(
                    JobWorkAssignment.job_id == job_id,
                    JobWorkAssignment.user_id == first,
                    JobWorkAssignment.state == "released",
                )
            )
        ).all()
        assert list(reasons) == ["reassigned"]

    # Druga osoba dołącza obok — pierwsza zostaje prowadzącą.
    joined = await add(second)
    assert joined.status_code == 200, joined.text
    assert await people() == [(first, "owner"), (second, "assignment")]
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).recruiter_id == first


async def test_competence_team_assign_and_exclude(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    person = await _seed_recruiter()
    team = (
        await app_client.get("/api/competence-team", headers=app_auth_headers)
    ).json()
    qa = next(c for c in team["categories"] if c["slug"] == "security_quality")
    assert person in {p["user_id"] for p in team["unassigned"]}

    put = await app_client.put(
        "/api/competence-team/assignments",
        json={"user_id": person, "competence_category_id": qa["id"], "priority": 1},
        headers=app_auth_headers,
    )
    assert put.status_code == 200, put.text
    team = (
        await app_client.get("/api/competence-team", headers=app_auth_headers)
    ).json()
    qa = next(c for c in team["categories"] if c["slug"] == "security_quality")
    assert person in {p["user_id"] for p in qa["first"]}

    excluded = await app_client.patch(
        f"/api/competence-team/people/{person}/allocation",
        json={"excluded": True},
        headers=app_auth_headers,
    )
    assert excluded.json()["allocation_excluded"] is True
    team = (
        await app_client.get("/api/competence-team", headers=app_auth_headers)
    ).json()
    assert person in {p["user_id"] for p in team["excluded"]}


async def test_rules_validation_is_polish_and_strict(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    bad = await app_client.put(
        "/api/competence-team/rules",
        json={"sourcer_threshold": 0, "review_time": "8:30"},
        headers=app_auth_headers,
    )
    assert bad.status_code == 422
    good = await app_client.put(
        "/api/competence-team/rules",
        json={"sourcer_threshold": 15, "review_time": "08:30"},
        headers=app_auth_headers,
    )
    assert good.json() == {"sourcer_threshold": 15, "review_time": "08:30"}


async def test_manual_add_needs_a_request_in_work(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    person = await _seed_recruiter()
    for job_id in (
        await _seed_job(work_state="to_review"),
        await _seed_job(work_state="searching", champion=True),
    ):
        resp = await app_client.post(
            f"/api/request-board/jobs/{job_id}/people",
            json={"user_id": person, "role": "recruiter"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 409


async def test_lead_recruiter_is_adopted_and_manual_removal_sticks() -> None:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.job_work_assignment import JobWorkAssignment
    from app.services.request_allocation import (
        _adopt_owners,
        _blocked,
        manual_remove,
    )

    job_id = await _seed_job(work_state="searching")
    owner = await _seed_recruiter()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.recruiter_id = owner
        await db.commit()

    async def live_rows() -> list[tuple[int, str]]:
        async with AsyncSessionLocal() as db:
            return [
                (row.user_id, row.source)
                for row in (
                    await db.scalars(
                        select(JobWorkAssignment).where(
                            JobWorkAssignment.job_id == job_id,
                            JobWorkAssignment.state != "released",
                        )
                    )
                ).all()
            ]

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        await _adopt_owners(db, blocked=await _blocked(db), now=now)
        await db.commit()
    assert await live_rows() == [(owner, "owner")]

    async with AsyncSessionLocal() as db:
        assert await manual_remove(db, job_id=job_id, user_id=owner)
        await db.commit()
    async with AsyncSessionLocal() as db:
        blocked = await _blocked(db)
        assert (job_id, owner) in blocked
        await _adopt_owners(db, blocked=blocked, now=datetime.now(timezone.utc))
        await db.commit()
    assert await live_rows() == []


async def test_reopened_job_goes_back_to_review(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Zamknięcie → „Zakończony”, ponowne otwarcie → „Do przejrzenia”.

    Audyt 24.09.2026: PATCH ``closed → published`` zostawiał ``finished``,
    więc opublikowana rekrutacja wypadała z puli przydziału, pulpitu
    „Requesty” i nocnego przeglądu bazy, bez żadnego sygnału.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    job_id = await _seed_job(work_state="searching")

    closed = await app_client.patch(
        f"/api/jobs/{job_id}", json={"status": "closed"}, headers=app_auth_headers
    )
    assert closed.status_code == 200, closed.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).work_state == "finished"

    reopened = await app_client.patch(
        f"/api/jobs/{job_id}", json={"status": "published"}, headers=app_auth_headers
    )
    assert reopened.status_code == 200, reopened.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).work_state == "to_review"


async def test_republish_of_closed_job_goes_back_to_review(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """``POST /publish`` na zamkniętej rekrutacji też zdejmuje „Zakończony”."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    job_id = await _seed_job(work_state="searching")
    closed = await app_client.patch(
        f"/api/jobs/{job_id}", json={"status": "closed"}, headers=app_auth_headers
    )
    assert closed.status_code == 200, closed.text

    published = await app_client.post(
        f"/api/jobs/{job_id}/publish", headers=app_auth_headers
    )
    assert published.status_code == 200, published.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.work_state == "to_review"
        assert job.closed_at is None


async def _live_rows(job_id: int) -> list[tuple[int, str, str]]:
    from app.core.database import AsyncSessionLocal
    from app.models.job_work_assignment import JobWorkAssignment

    async with AsyncSessionLocal() as db:
        return sorted(
            (row.user_id, row.source, row.state)
            for row in (
                await db.scalars(
                    select(JobWorkAssignment).where(
                        JobWorkAssignment.job_id == job_id,
                        JobWorkAssignment.state != "released",
                    )
                )
            ).all()
        )


async def test_automat_release_is_not_undone_by_owner_adoption() -> None:
    """Audyt 24.09: automat wpisał A jako prowadzącego, potem zwolnił go za
    urlop. Zwolnienie zdejmuje też prowadzącego (nikt go nie zmieniał), a
    adopcja nie przywraca A jako ``owner`` w tym samym stanie requestu."""
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.request_allocation import (
        _adopt_owners,
        _apply,
        _auto_released,
        _blocked,
    )
    from app.services.request_allocation_plan import Change

    job_id = await _seed_job(work_state="searching")
    person = await _seed_recruiter()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        # Tryb auto: przydział + wpisanie prowadzącego przez automat.
        await _apply(
            db,
            [Change("assign", job_id, person, "recruiter", "")],
            mode="auto",
            now=now,
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).recruiter_id == person
    assert await _live_rows(job_id) == [(person, "auto", "active")]

    async with AsyncSessionLocal() as db:
        await _apply(
            db,
            [Change("release", job_id, person, "recruiter", "unavailable")],
            mode="auto",
            now=datetime.now(timezone.utc),
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).recruiter_id is None
    assert await _live_rows(job_id) == []

    # Ktoś ręcznie ustawia A prowadzącym (albo ślad został) — adopcja i tak
    # nie przywraca osoby zwolnionej przez automat w tym stanie requestu.
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.recruiter_id = person
        await db.commit()
    async with AsyncSessionLocal() as db:
        released = await _auto_released(db)
        assert (job_id, person) in released
        await _adopt_owners(
            db,
            blocked=await _blocked(db),
            now=datetime.now(timezone.utc),
            auto_released=released,
        )
        await db.commit()
    assert await _live_rows(job_id) == []

    # Zmiana stanu requestu kończy epizod — prowadzący znów jest przy nim.
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.work_state_changed_at = datetime.now(timezone.utc)
        await db.commit()
    async with AsyncSessionLocal() as db:
        await _adopt_owners(
            db,
            blocked=await _blocked(db),
            now=datetime.now(timezone.utc),
            auto_released=await _auto_released(db),
        )
        await db.commit()
    assert await _live_rows(job_id) == [(person, "owner", "active")]


async def test_deactivated_owner_row_is_released() -> None:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.user import User
    from app.services.request_allocation import _adopt_owners, _blocked

    job_id = await _seed_job(work_state="searching")
    owner = await _seed_recruiter()
    async with AsyncSessionLocal() as db:
        (await db.get(Job, job_id)).recruiter_id = owner
        await db.commit()
    async with AsyncSessionLocal() as db:
        await _adopt_owners(
            db, blocked=await _blocked(db), now=datetime.now(timezone.utc)
        )
        await db.commit()
    assert await _live_rows(job_id) == [(owner, "owner", "active")]
    async with AsyncSessionLocal() as db:
        (await db.get(User, owner)).is_active = False
        await db.commit()
    async with AsyncSessionLocal() as db:
        await _adopt_owners(
            db, blocked=await _blocked(db), now=datetime.now(timezone.utc)
        )
        await db.commit()
    assert await _live_rows(job_id) == []


async def test_base_matches_come_from_open_full_base_proposals() -> None:
    """Audyt 24.09: przegląd ``origin=auto`` żyje 2 dni, propozycje zostają —
    liczba pasujących w bazie idzie z propozycji ``full_base``."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job_proposal import JobProposal
    from app.services.request_allocation import _requests

    reviewed = await _seed_job(work_state="searching")
    never = await _seed_job(work_state="searching")
    async with AsyncSessionLocal() as db:
        for status, source in (
            ("proposed", "full_base"),
            ("proposed", "full_base"),
            ("dismissed", "full_base"),
            ("proposed", "new_cv"),
        ):
            cand = Candidate(name="Ala", lastname=f"Rb{uuid.uuid4().hex[:8]}")
            db.add(cand)
            await db.flush()
            db.add(
                JobProposal(
                    job_id=reviewed, candidate_id=cand.id, source=source, status=status
                )
            )
        await db.commit()
    async with AsyncSessionLocal() as db:
        infos = {r.job_id: r for r in await _requests(db)}
    assert infos[reviewed].base_matches == 2
    assert infos[never].base_matches is None


async def test_manual_add_twice_is_idempotent_and_takes_over_auto_row(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.job_work_assignment import JobWorkAssignment

    job_id = await _seed_job(work_state="searching")
    person = await _seed_recruiter()
    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=person,
                role="recruiter",
                source="auto",
                state="proposed",
                assigned_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()
    for _ in range(2):
        resp = await app_client.post(
            f"/api/request-board/jobs/{job_id}/people",
            json={"user_id": person, "role": "recruiter"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
    assert await _live_rows(job_id) == [(person, "manual", "active")]


async def test_review_tab_pages_with_limit_and_offset(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Zakładka „Zakończone” niesie ~4 tys. wierszy — lista idzie stronami."""
    await _seed_job(work_state="finished")
    await _seed_job(work_state="finished")
    first = await app_client.get(
        "/api/request-work-states",
        params={"tab": "finished", "limit": 1},
        headers=app_auth_headers,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert len(body["rows"]) == 1
    assert body["total"] == body["counts"]["finished"] >= 2
    assert body["has_more"] is True
    second = await app_client.get(
        "/api/request-work-states",
        params={"tab": "finished", "limit": 1, "offset": 1},
        headers=app_auth_headers,
    )
    assert second.json()["rows"][0]["job_id"] != body["rows"][0]["job_id"]
    too_big = await app_client.get(
        "/api/request-work-states",
        params={"tab": "finished", "limit": 5000},
        headers=app_auth_headers,
    )
    assert too_big.status_code == 422


async def test_closed_recruitment_state_change_is_refused_until_reopened(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Audyt 25.09.2026: „Szukamy” przy zamkniętej rekrutacji z zakładki
    „Zakończone” zapisywało `searching` przy `status=closed` i wiersz znikał
    z listy. Teraz 409 bez zapisu; „Zakończony” zostaje dozwolony."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    job_id = await _seed_job(work_state="finished")
    open_id = await _seed_job()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.status = JobStatus.closed
        title = job.title
        await db.commit()

    listed = await app_client.get(
        "/api/request-work-states",
        params={"tab": "finished", "q": title},
        headers=app_auth_headers,
    )
    row = next(r for r in listed.json()["rows"] if r["job_id"] == job_id)
    assert row["closed"] is True

    refused = await app_client.patch(
        "/api/request-work-states",
        json={
            "changes": [
                {"job_id": open_id, "state": "searching"},
                {"job_id": job_id, "state": "searching"},
            ]
        },
        headers=app_auth_headers,
    )
    assert refused.status_code == 409, refused.text
    assert "Najpierw otwórz rekrutację" in refused.json()["detail"]
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).work_state == "finished"
        # Paczka jest atomowa — otwarta rekrutacja też się nie zmieniła.
        assert (await db.get(Job, open_id)).work_state == "to_review"

    finished = await app_client.patch(
        "/api/request-work-states",
        json={"changes": [{"job_id": job_id, "state": "finished"}]},
        headers=app_auth_headers,
    )
    assert finished.status_code == 200, finished.text


async def test_released_proposal_does_not_mark_a_human_owner_as_automat() -> None:
    """Runda 9 (R9-V2-1): propozycja z trybu podglądu zwolniona przy wyłączeniu
    automatu nigdy nie wpisała prowadzącego. Prowadzący ustawiony potem przez
    człowieka wraca adopcją jako ``owner`` — inaczej zwolnienie za urlop
    zdejmowało mu ``jobs.recruiter_id``."""
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.request_allocation import (
        _adopt_owners,
        _apply,
        _auto_released,
        _blocked,
    )
    from app.services.request_allocation_plan import (
        PROPOSAL_RELEASE_PREFIX,
        Change,
        release_reason_label,
    )

    job_id = await _seed_job(work_state="searching")
    person = await _seed_recruiter()
    async with AsyncSessionLocal() as db:
        await _apply(
            db,
            [Change("assign", job_id, person, "recruiter", "")],
            mode="shadow",
            now=datetime.now(timezone.utc),
        )
        await db.commit()
    assert await _live_rows(job_id) == [(person, "auto", "proposed")]
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).recruiter_id is None
        await _apply(
            db,
            [Change("release", job_id, person, "recruiter", "mode_off")],
            mode="off",
            now=datetime.now(timezone.utc),
        )
        job = await db.get(Job, job_id)
        job.recruiter_id = person  # decyzja człowieka
        await db.commit()
    async with AsyncSessionLocal() as db:
        await _adopt_owners(
            db,
            blocked=await _blocked(db),
            now=datetime.now(timezone.utc),
            auto_released=await _auto_released(db),
        )
        await db.commit()
    assert await _live_rows(job_id) == [(person, "owner", "active")]
    assert release_reason_label(f"{PROPOSAL_RELEASE_PREFIX}mode_off") == (
        "Automat wyłączony"
    )
