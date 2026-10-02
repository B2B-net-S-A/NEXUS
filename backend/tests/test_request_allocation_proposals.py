"""Propozycje automatu przydziału do akceptacji (decyzja Artura 02.10.2026).

Automat proponuje jedną osobę do requestu bez obsady; Head of Recruitment
albo admin akceptuje, zamienia albo odrzuca. Do akceptacji nikt nie jest
przypisany i nikt nie dostaje dzwonka.

Baza testowa jest wspólna i nieczyszczona — każdy test zakłada własne
rekrutacje i osoby i asertuje wyłącznie po nich.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.client import Client
from app.models.competence_category import CompetenceCategory, UserCompetenceCategory
from app.models.job import Job, JobPriority, JobStatus
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.job_work_assignment import JobWorkAssignment
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


# ── Dane testowe ─────────────────────────────────────────────────────────────


async def _user(role: UserRole) -> tuple[int, dict[str, str]]:
    marker = uuid.uuid4().hex[:10]
    creds = {
        "email": f"prop-{role.value}-{marker}@example.com",
        "password": f"T3st_{marker}!Prop",
    }
    async with AsyncSessionLocal() as db:
        user = User(
            email=creds["email"],
            password_hash=hash_password(creds["password"]),
            name=f"Prop {role.value} {marker}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        return user.id, creds


async def _login(client: AsyncClient, creds: dict[str, str]) -> dict[str, str]:
    resp = await client.post("/api/auth/login", json=creds)
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _category() -> int:
    """Własna kategoria — tylko osoby z tego testu mają ją w 1. priorytecie."""
    marker = uuid.uuid4().hex[:12]
    async with AsyncSessionLocal() as db:
        category = CompetenceCategory(
            slug=f"prop-{marker}",
            name_pl=f"Propozycje {marker}",
            name_en=f"Proposals {marker}",
            description="CI fixture",
        )
        db.add(category)
        await db.commit()
        return category.id


async def _give_category(user_id: int, category_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            UserCompetenceCategory(
                user_id=user_id,
                competence_category_id=category_id,
                priority=1,
                is_primary=True,
            )
        )
        await db.commit()


async def _job(**fields) -> int:
    """Request w puli automatu: opublikowany, „Szukamy kandydatów”, bez championa."""
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"prop-client-{marker}")
        db.add(client)
        await db.flush()
        job = Job(
            title=fields.pop("title", f"Prop request {marker}"),
            client_id=client.id,
            status=fields.pop("status", JobStatus.published),
            work_state=fields.pop("work_state", "searching"),
            **fields,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _propose(job_id: int, user_id: int, *, role: str = "recruiter") -> datetime:
    proposed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=user_id,
                role=role,
                source="auto",
                state="proposed",
                assigned_at=proposed_at,
            )
        )
        await db.commit()
    return proposed_at


async def _rows(job_id: int) -> list[JobWorkAssignment]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(JobWorkAssignment)
                    .where(JobWorkAssignment.job_id == job_id)
                    .order_by(JobWorkAssignment.id)
                )
            ).all()
        )


async def _owner(job_id: int) -> int | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Job.recruiter_id).where(Job.id == job_id))


async def _decisions(job_id: int) -> list[Activity]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Activity)
                    .where(
                        Activity.entity_type == "job",
                        Activity.entity_id == job_id,
                        Activity.action == "allocation_proposal_decided",
                    )
                    .order_by(Activity.id)
                )
            ).all()
        )


async def _assignment_notices(user_id: int, job_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == user_id,
                        Notification.notification_type
                        == NotificationType.request_assignment_changed,
                        Notification.related_entity_type == "job",
                        Notification.related_entity_id == job_id,
                    )
                )
            ).all()
        )


def _decide_url(job_id: int, user_id: int) -> str:
    return f"/api/request-board/jobs/{job_id}/proposals/{user_id}"


# ── Akceptacja ───────────────────────────────────────────────────────────────


async def test_accept_turns_the_proposal_into_a_human_assignment(
    app_client: AsyncClient,
) -> None:
    hor_id, hor_creds = await _user(UserRole.head_of_recruitment)
    hor = await _login(app_client, hor_creds)
    person, _ = await _user(UserRole.recruiter)
    job_id = await _job(working_title="Java Spring")
    proposed_at = await _propose(job_id, person)
    # Do akceptacji nikt nie jest przypisany i nikt nie dostał dzwonka.
    assert await _owner(job_id) is None
    assert await _assignment_notices(person, job_id) == []

    resp = await app_client.post(
        _decide_url(job_id, person), json={"decision": "accept"}, headers=hor
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"decision": "accept", "assigned_user_id": person}

    (row,) = await _rows(job_id)
    assert (row.user_id, row.state, row.source) == (person, "active", "manual")
    assert row.assigned_by == hor_id
    # Osoba pracuje od akceptacji, nie od chwili, gdy automat ją zaproponował.
    assert row.assigned_at > proposed_at
    # Pierwszy rekruter zostaje prowadzącym rekrutacji.
    assert await _owner(job_id) == person

    (decision,) = await _decisions(job_id)
    assert decision.user_id == hor_id
    assert decision.details == {"user_id": person, "decision": "accept"}

    (notice,) = await _assignment_notices(person, job_id)
    assert notice.title == "Nowy request do pracy"
    assert notice.link == f"/jobs/{job_id}"
    assert notice.message.startswith("Java Spring · prop-client-")


async def test_accept_on_a_vanished_proposal_is_409_and_assigns_nobody(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    person, _ = await _user(UserRole.recruiter)
    job_id = await _job()
    # Propozycji nigdy nie było.
    missing = await app_client.post(
        _decide_url(job_id, person),
        json={"decision": "accept"},
        headers=app_auth_headers,
    )
    assert missing.status_code == 409, missing.text
    assert "nieaktualna" in missing.json()["detail"]
    assert await _rows(job_id) == []

    # Propozycję automat już wycofał — spóźnione kliknięcie nie wstawia wiersza.
    await _propose(job_id, person)
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobWorkAssignment).where(JobWorkAssignment.job_id == job_id)
        )
        row.state = "released"
        row.released_at = datetime.now(timezone.utc)
        row.release_reason = "proposal:superseded"
        await db.commit()
    late = await app_client.post(
        _decide_url(job_id, person),
        json={"decision": "accept"},
        headers=app_auth_headers,
    )
    assert late.status_code == 409, late.text
    assert [r.state for r in await _rows(job_id)] == ["released"]
    assert await _owner(job_id) is None
    assert await _decisions(job_id) == []


async def test_accept_is_refused_once_someone_works_on_the_request(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Delivery Lead przypisał rekrutera, zanim automat wycofał propozycję."""
    proposed, _ = await _user(UserRole.recruiter)
    lead, _ = await _user(UserRole.recruiter)
    job_id = await _job()
    await _propose(job_id, proposed)
    async with AsyncSessionLocal() as db:
        (await db.get(Job, job_id)).recruiter_id = lead
        await db.commit()

    resp = await app_client.post(
        _decide_url(job_id, proposed),
        json={"decision": "accept"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    (row,) = await _rows(job_id)
    assert row.state == "proposed"
    assert await _owner(job_id) == lead


async def test_accept_is_refused_when_the_request_left_the_pool(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    person, _ = await _user(UserRole.recruiter)
    job_id = await _job(work_state="client_silent")
    await _propose(job_id, person)
    resp = await app_client.post(
        _decide_url(job_id, person),
        json={"decision": "accept"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert [r.state for r in await _rows(job_id)] == ["proposed"]


# ── Odrzucenie ───────────────────────────────────────────────────────────────


async def test_reject_blocks_the_automat_but_not_a_human_owner(
    app_client: AsyncClient,
) -> None:
    from app.services.request_allocation import (
        REJECTED_PROPOSAL,
        _adopt_owners,
        _auto_released,
        _blocked,
    )

    hor_id, hor_creds = await _user(UserRole.head_of_recruitment)
    hor = await _login(app_client, hor_creds)
    person, _ = await _user(UserRole.recruiter)
    job_id = await _job()
    await _propose(job_id, person)

    resp = await app_client.post(
        _decide_url(job_id, person), json={"decision": "reject"}, headers=hor
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"decision": "reject", "assigned_user_id": None}
    (row,) = await _rows(job_id)
    assert (row.state, row.release_reason) == ("released", "proposal:rejected")
    assert await _owner(job_id) is None
    assert await _assignment_notices(person, job_id) == []
    (decision,) = await _decisions(job_id)
    assert decision.details == {"user_id": person, "decision": "reject"}
    assert decision.user_id == hor_id

    # Drugi raz nie ma czego odrzucać.
    again = await app_client.post(
        _decide_url(job_id, person), json={"decision": "reject"}, headers=hor
    )
    assert again.status_code == 409, again.text

    async with AsyncSessionLocal() as db:
        # Planer nie zaproponuje tej osoby do tego requestu ponownie…
        assert (job_id, person) in await _blocked(db, REJECTED_PROPOSAL)
        # …ale to nie jest „zdjęcie ręczne”: człowiek może ją zrobić prowadzącą
        # i adopcja prowadzącego jej nie pomija.
        blocked = await _blocked(db)
        assert (job_id, person) not in blocked
        (await db.get(Job, job_id)).recruiter_id = person
        await db.flush()
        await _adopt_owners(
            db,
            blocked=blocked,
            now=datetime.now(timezone.utc),
            auto_released=await _auto_released(db),
        )
        await db.commit()
    live = [r for r in await _rows(job_id) if r.state != "released"]
    assert [(r.user_id, r.source, r.state) for r in live] == [
        (person, "owner", "active")
    ]


# ── Zamiana ──────────────────────────────────────────────────────────────────


async def test_replace_assigns_the_chosen_person_instead(
    app_client: AsyncClient,
) -> None:
    from app.services.request_allocation import REJECTED_PROPOSAL, _blocked

    hor_id, hor_creds = await _user(UserRole.head_of_recruitment)
    hor = await _login(app_client, hor_creds)
    proposed, _ = await _user(UserRole.recruiter)
    chosen, _ = await _user(UserRole.recruiter)
    job_id = await _job()
    await _propose(job_id, proposed)

    resp = await app_client.post(
        _decide_url(job_id, proposed),
        json={"decision": "replace", "replacement_user_id": chosen},
        headers=hor,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"decision": "replace", "assigned_user_id": chosen}

    by_user = {r.user_id: r for r in await _rows(job_id)}
    assert (by_user[proposed].state, by_user[proposed].release_reason) == (
        "released",
        "proposal:replaced",
    )
    assert (by_user[chosen].state, by_user[chosen].source, by_user[chosen].role) == (
        "active",
        "manual",
        "recruiter",
    )
    assert by_user[chosen].assigned_by == hor_id
    assert await _owner(job_id) == chosen
    (decision,) = await _decisions(job_id)
    assert decision.details == {
        "user_id": proposed,
        "decision": "replace",
        "replacement_user_id": chosen,
    }
    # Dzwonek dostaje osoba, która pracuje — nie ta, którą automat proponował.
    assert len(await _assignment_notices(chosen, job_id)) == 1
    assert await _assignment_notices(proposed, job_id) == []
    # Zamiana nie blokuje: automat może kiedyś zaproponować tę osobę ponownie.
    async with AsyncSessionLocal() as db:
        assert (job_id, proposed) not in await _blocked(db, REJECTED_PROPOSAL)


async def test_replace_validates_the_replacement(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    proposed, _ = await _user(UserRole.recruiter)
    not_an_operator, _ = await _user(UserRole.head_of_recruitment)
    job_id = await _job()
    await _propose(job_id, proposed)

    for body, status in (
        ({"decision": "replace"}, 422),
        ({"decision": "replace", "replacement_user_id": proposed}, 422),
        ({"decision": "replace", "replacement_user_id": not_an_operator}, 422),
        ({"decision": "replace", "replacement_user_id": 2_000_000_000}, 404),
    ):
        resp = await app_client.post(
            _decide_url(job_id, proposed), json=body, headers=app_auth_headers
        )
        assert resp.status_code == status, (body, resp.text)
    # Nieudana zamiana niczego nie zmienia — propozycja czeka dalej.
    (row,) = await _rows(job_id)
    assert row.state == "proposed"
    assert await _decisions(job_id) == []


# ── Akceptacja zbiorcza ──────────────────────────────────────────────────────


async def test_bulk_accept_reports_gone_items_without_stopping(
    app_client: AsyncClient,
) -> None:
    hor_id, hor_creds = await _user(UserRole.head_of_recruitment)
    hor = await _login(app_client, hor_creds)
    first, _ = await _user(UserRole.recruiter)
    second, _ = await _user(UserRole.recruiter)
    late, _ = await _user(UserRole.recruiter)
    job_a, job_b, job_gone = await _job(), await _job(), await _job()
    await _propose(job_a, first)
    await _propose(job_b, second)
    # Trzeciej propozycji już nie ma (automat ją wycofał).

    resp = await app_client.post(
        "/api/request-board/proposals/accept",
        json={
            "items": [
                {"job_id": job_b, "user_id": second},
                {"job_id": job_gone, "user_id": late},
                {"job_id": job_a, "user_id": first},
            ]
        },
        headers=hor,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "results": [
            {"job_id": job_b, "user_id": second, "status": "accepted"},
            {"job_id": job_gone, "user_id": late, "status": "gone"},
            {"job_id": job_a, "user_id": first, "status": "accepted"},
        ]
    }
    for job_id, person in ((job_a, first), (job_b, second)):
        (row,) = await _rows(job_id)
        assert (row.state, row.source, row.assigned_by) == ("active", "manual", hor_id)
        assert await _owner(job_id) == person
        (decision,) = await _decisions(job_id)
        assert decision.details == {"user_id": person, "decision": "accept"}
        assert len(await _assignment_notices(person, job_id)) == 1
    assert await _rows(job_gone) == []
    assert await _decisions(job_gone) == []
    assert await _assignment_notices(late, job_gone) == []


async def test_bulk_accept_rejects_an_empty_or_oversized_batch(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    empty = await app_client.post(
        "/api/request-board/proposals/accept",
        json={"items": []},
        headers=app_auth_headers,
    )
    assert empty.status_code == 422
    too_many = await app_client.post(
        "/api/request-board/proposals/accept",
        json={"items": [{"job_id": 1, "user_id": n} for n in range(1, 102)]},
        headers=app_auth_headers,
    )
    assert too_many.status_code == 422


# ── Uprawnienia ──────────────────────────────────────────────────────────────


async def test_only_head_of_recruitment_and_admin_decide_about_proposals(
    app_client: AsyncClient,
) -> None:
    _, recruiter_creds = await _user(UserRole.recruiter)
    _, lead_creds = await _user(UserRole.delivery_lead)
    _, hor_creds = await _user(UserRole.head_of_recruitment)
    person, _ = await _user(UserRole.recruiter)
    job_id = await _job()
    await _propose(job_id, person)

    for creds in (recruiter_creds, lead_creds):
        headers = await _login(app_client, creds)
        single = await app_client.post(
            _decide_url(job_id, person), json={"decision": "accept"}, headers=headers
        )
        assert single.status_code == 403, single.text
        bulk = await app_client.post(
            "/api/request-board/proposals/accept",
            json={"items": [{"job_id": job_id, "user_id": person}]},
            headers=headers,
        )
        assert bulk.status_code == 403, bulk.text
        # Zdjęcie propozycji z pulpitu to też decyzja o propozycji.
        removed = await app_client.delete(
            f"/api/request-board/jobs/{job_id}/people/{person}", headers=headers
        )
        assert removed.status_code == 403, removed.text
    (row,) = await _rows(job_id)
    assert row.state == "proposed"

    hor = await _login(app_client, hor_creds)
    removed = await app_client.delete(
        f"/api/request-board/jobs/{job_id}/people/{person}", headers=hor
    )
    assert removed.status_code == 200, removed.text
    assert removed.json() == {"removed": True}
    (row,) = await _rows(job_id)
    assert (row.state, row.release_reason) == ("released", "proposal:rejected")
    (decision,) = await _decisions(job_id)
    assert decision.details == {"user_id": person, "decision": "reject"}


async def test_delivery_lead_still_removes_a_working_person_from_the_board(
    app_client: AsyncClient,
) -> None:
    """Propozycje to decyzja Head of Recruitment, ale obsadę requestu Delivery
    Lead prowadzi jak dotąd — także prowadzącego bez wiersza przypisania."""
    _, lead_creds = await _user(UserRole.delivery_lead)
    lead = await _login(app_client, lead_creds)
    owner, _ = await _user(UserRole.recruiter)
    job_id = await _job(recruiter_id=owner)

    removed = await app_client.delete(
        f"/api/request-board/jobs/{job_id}/people/{owner}", headers=lead
    )
    assert removed.status_code == 200, removed.text
    assert removed.json() == {"removed": True}
    assert await _owner(job_id) is None


# ── Jedno źródło dla panelu i dzwonka ────────────────────────────────────────


async def test_pending_list_describes_the_proposal_and_hides_it_when_staffed() -> None:
    from app.services.request_allocation_proposals import load_pending, pending_pairs

    category = await _category()
    person, _ = await _user(UserRole.recruiter)
    await _give_category(person, category)
    lead_id, _ = await _user(UserRole.delivery_lead)
    colleague, _ = await _user(UserRole.recruiter)
    # Proponowana osoba prowadzi już jeden request „Szukamy” — to jej obłożenie.
    await _job(recruiter_id=person)
    job_id = await _job(
        title="ZOB-0000",
        working_title="Tester automatyzujący",
        competence_category_id=category,
        delivery_lead_id=lead_id,
        priority=JobPriority.urgent,
        deadline=date(2031, 3, 14),
    )
    proposed_at = await _propose(job_id, person)

    async with AsyncSessionLocal() as db:
        pending = {(p.job_id, p.user_id): p for p in await load_pending(db)}
        assert await pending_pairs(db, [job_id]) == {(job_id, person)}
        lead_name = await db.scalar(select(User.name).where(User.id == lead_id))
        person_name = await db.scalar(select(User.name).where(User.id == person))
        category_row = await db.get(CompetenceCategory, category)
    mine = pending[(job_id, person)]
    assert mine.title == "Tester automatyzujący"
    assert mine.client_name.startswith("prop-client-")
    assert (mine.category_id, mine.category_name, mine.category_slug) == (
        category,
        category_row.name_pl,
        category_row.slug,
    )
    assert mine.delivery_lead_name == lead_name
    assert mine.priority_level == "p1"
    assert mine.deadline == date(2031, 3, 14)
    assert mine.sent == 0
    assert (mine.user_name, mine.role) == (person_name, "recruiter")
    assert mine.fit == "first"
    assert mine.load == 1
    assert mine.leave_until is None
    # Nocnego przeglądu bazy nie było — nie wiadomo, ilu pasuje.
    assert mine.base_matches is None
    assert mine.proposed_at == proposed_at

    # Rekruter dopisał się do requestu sam (ręczny współpracownik) — propozycja
    # znika z panelu od razu, bez czekania na przebieg automatu.
    async with AsyncSessionLocal() as db:
        db.add(
            JobCollaborator(
                job_id=job_id, user_id=colleague, source=JobCollaboratorSource.manual
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (job_id, person) not in {
            (p.job_id, p.user_id) for p in await load_pending(db)
        }
        assert await pending_pairs(db, [job_id]) == set()
    # Sam wiersz propozycji zostaje do najbliższego przebiegu automatu.
    (row,) = await _rows(job_id)
    assert row.state == "proposed"


async def test_pending_list_puts_p1_first_then_the_oldest_proposal() -> None:
    from app.services.request_allocation_proposals import load_pending

    person, _ = await _user(UserRole.recruiter)
    standard_old = await _job()
    standard_new = await _job()
    urgent = await _job(priority=JobPriority.urgent)
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        for job_id, age in ((standard_new, 1), (urgent, 2), (standard_old, 3)):
            db.add(
                JobWorkAssignment(
                    job_id=job_id,
                    user_id=person,
                    role="recruiter",
                    source="auto",
                    state="proposed",
                    assigned_at=now - timedelta(hours=age),
                )
            )
        await db.commit()
    async with AsyncSessionLocal() as db:
        order = [p.job_id for p in await load_pending(db) if p.user_id == person]
    assert order == [urgent, standard_old, standard_new]


async def test_pending_list_skips_requests_out_of_the_pool_and_dead_accounts() -> None:
    from app.services.request_allocation_proposals import load_pending

    person, _ = await _user(UserRole.recruiter)
    dead, _ = await _user(UserRole.recruiter)
    in_pool = await _job()
    with_champion = await _job(champion_found_at=datetime.now(timezone.utc))
    silent = await _job(work_state="client_silent")
    for job_id in (in_pool, with_champion, silent):
        await _propose(job_id, person)
    dead_job = await _job()
    await _propose(dead_job, dead)
    async with AsyncSessionLocal() as db:
        (await db.get(User, dead)).is_active = False
        await db.commit()
    async with AsyncSessionLocal() as db:
        pending = {(p.job_id, p.user_id) for p in await load_pending(db)}
    mine = {in_pool, with_champion, silent, dead_job}
    assert {pair for pair in pending if pair[0] in mine} == {(in_pool, person)}


async def test_planner_sees_people_who_work_without_an_assignment_row() -> None:
    """Reguła „kto pracuje” jest jedna: request z ręcznym współpracownikiem
    albo z prowadzącym, którego para żyje jeszcze jako propozycja, jest dla
    planera obsadzony — propozycja przy nim znika, a osoba ma go w obłożeniu."""
    from app.services.request_allocation import _unseen_workers
    from app.services.request_allocation_plan import LiveAssignment, RequestInfo

    owner, _ = await _user(UserRole.recruiter)
    collaborator, _ = await _user(UserRole.recruiter)
    adopted, _ = await _user(UserRole.recruiter)
    # Delivery Lead zrobił prowadzącą osobę, którą automat tylko proponował.
    proposed_owner_job = await _job(recruiter_id=owner)
    await _propose(proposed_owner_job, owner)
    collaborator_job = await _job()
    # Prowadzący z aktywnym wierszem jest widoczny dla planera jako wiersz.
    adopted_job = await _job(recruiter_id=adopted)
    empty_job = await _job()
    async with AsyncSessionLocal() as db:
        db.add(
            JobCollaborator(
                job_id=collaborator_job,
                user_id=collaborator,
                source=JobCollaboratorSource.manual,
            )
        )
        db.add(
            JobWorkAssignment(
                job_id=adopted_job,
                user_id=adopted,
                role="recruiter",
                source="owner",
                state="active",
                assigned_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

    jobs = (proposed_owner_job, collaborator_job, adopted_job, empty_job)
    requests = [
        RequestInfo(
            job_id=job_id,
            categories=frozenset(),
            primary_category=None,
            sent=0,
            deadline=None,
            base_matches=None,
        )
        for job_id in jobs
    ]
    live = [
        LiveAssignment(proposed_owner_job, owner, "recruiter", "auto", "proposed"),
        LiveAssignment(adopted_job, adopted, "recruiter", "owner", "active"),
    ]
    async with AsyncSessionLocal() as db:
        staffed, extra_load = await _unseen_workers(db, requests, live)
    assert staffed == frozenset({proposed_owner_job, collaborator_job})
    assert extra_load == {owner: 1, collaborator: 1}


# ── Cały przebieg automatu ───────────────────────────────────────────────────


async def test_automat_proposes_once_notifies_hor_and_withdraws_when_someone_works(
    monkeypatch,
) -> None:
    """Przebieg w trybie podglądu na prawdziwej bazie: jedna propozycja na
    request, dzwonek tylko dla Head of Recruitment, a po przypisaniu rekrutera
    przez człowieka propozycja jest wycofywana.

    Automat liczy całą pulę, więc przebiegi idą w jednej transakcji wycofanej
    na końcu — cudze requesty we wspólnej bazie zostają nietknięte.
    """
    from app.services.recruitment_allocation import allocation_lock
    from app.services.request_allocation import run_request_allocation
    from app.services.request_allocation_notices import PROPOSALS_LINK
    from app.services.request_allocation_proposals import load_pending

    monkeypatch.setattr(settings, "COMPASS_AVAILABILITY_ENABLED", False)
    hor_id, _ = await _user(UserRole.head_of_recruitment)
    category = await _category()
    person, _ = await _user(UserRole.recruiter)
    await _give_category(person, category)
    lead, _ = await _user(UserRole.recruiter)
    # P1 z najwcześniejszym terminem idzie w kolejce pierwsze, a kategorię ma
    # tylko `person` — wybór osoby nie zależy od cudzych danych w bazie.
    job_id = await _job(
        competence_category_id=category,
        priority=JobPriority.urgent,
        deadline=date(2000, 1, 1),
    )
    now = datetime.now(timezone.utc)
    # Poranny przegląd „już był” — test sprawdza propozycje, nie skrót dla DL.
    reviewed = {
        "last_review_date": now.astimezone(ZoneInfo(settings.BUSINESS_TZ))
        .date()
        .isoformat()
    }

    async def run(db, stats):
        return await run_request_allocation(
            db,
            mode="shadow",
            availability_fresh=False,
            available_ids=set(),
            stats=stats,
            now=now,
        )

    async def rows(db):
        return [
            (r.user_id, r.source, r.state, r.release_reason)
            for r in (
                await db.scalars(
                    select(JobWorkAssignment)
                    .where(JobWorkAssignment.job_id == job_id)
                    .order_by(JobWorkAssignment.id)
                    .execution_options(populate_existing=True)
                )
            ).all()
        ]

    async def hor_notices(db):
        return list(
            (
                await db.scalars(
                    select(Notification).where(
                        Notification.user_id == hor_id,
                        Notification.notification_type
                        == NotificationType.request_allocation_proposals,
                    )
                )
            ).all()
        )

    async with AsyncSessionLocal() as db:
        try:
            await allocation_lock(db)
            stats = await run(db, dict(reviewed))
            assert await rows(db) == [(person, "auto", "proposed", None)]
            assert stats["assigned"] >= 1
            # Propozycja nikogo nie przypisuje i nikogo nie budzi…
            assert (await db.get(Job, job_id, populate_existing=True)).recruiter_id is (
                None
            )
            assert (
                await db.scalar(
                    select(Notification.id).where(
                        Notification.user_id == person,
                        Notification.notification_type
                        == NotificationType.request_assignment_changed,
                    )
                )
                is None
            )
            # …poza Head of Recruitment: jeden wpis z liczbą czekających.
            (notice,) = await hor_notices(db)
            assert notice.title.startswith("Propozycje przydziału do akceptacji: ")
            assert notice.link == PROPOSALS_LINK
            assert (notice.related_entity_type, notice.related_entity_id) == (
                "user",
                hor_id,
            )
            assert (job_id, person) in {
                (p.job_id, p.user_id) for p in await load_pending(db)
            }

            # Drugi przebieg niczego nie dokłada: jedna propozycja, jeden wpis.
            stats = await run(db, stats)
            assert await rows(db) == [(person, "auto", "proposed", None)]
            assert len(await hor_notices(db)) == 1

            # Delivery Lead przypisuje rekrutera — propozycja znika z panelu
            # od razu, a automat wycofuje ją przy najbliższym przebiegu.
            (await db.get(Job, job_id)).recruiter_id = lead
            await db.flush()
            assert (job_id, person) not in {
                (p.job_id, p.user_id) for p in await load_pending(db)
            }
            await run(db, stats)
            assert await rows(db) == [
                (person, "auto", "released", "proposal:superseded"),
                (lead, "owner", "active", None),
            ]
        finally:
            await db.rollback()


async def test_automat_proposes_nobody_to_a_request_that_only_accepts_candidates(
    monkeypatch,
) -> None:
    from app.services.recruitment_allocation import allocation_lock
    from app.services.request_allocation import _requests, run_request_allocation

    monkeypatch.setattr(settings, "COMPASS_AVAILABILITY_ENABLED", False)
    category = await _category()
    person, _ = await _user(UserRole.recruiter)
    await _give_category(person, category)
    passive = await _job(competence_category_id=category, priority=JobPriority.low)
    urgent = await _job(competence_category_id=category, priority=JobPriority.high)
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(settings.BUSINESS_TZ)).date().isoformat()

    async with AsyncSessionLocal() as db:
        infos = {r.job_id: r for r in await _requests(db)}
        assert (infos[passive].passive, infos[passive].priority_rank) == (True, 1)
        # Historyczne ``high`` to dziś P1.
        assert (infos[urgent].passive, infos[urgent].priority_rank) == (False, 0)
        try:
            await allocation_lock(db)
            await run_request_allocation(
                db,
                mode="shadow",
                availability_fresh=False,
                available_ids=set(),
                stats={"last_review_date": today},
                now=now,
            )
            live = (
                await db.execute(
                    select(JobWorkAssignment.job_id, JobWorkAssignment.state).where(
                        JobWorkAssignment.job_id.in_([passive, urgent])
                    )
                )
            ).all()
            assert [tuple(row) for row in live] == [(urgent, "proposed")]
        finally:
            await db.rollback()


# ── Tryb automatyczny: dzwonek od razu ───────────────────────────────────────


async def test_automat_assignment_rings_the_person_right_away() -> None:
    """Tryb ``auto``: osoba dowiaduje się o requeście w chwili przydziału, nie
    rano. Propozycja trybu podglądu nikogo nie budzi — dopiero jej aktywacja."""
    from app.services.request_allocation import _apply
    from app.services.request_allocation_plan import Change

    assigned, _ = await _user(UserRole.recruiter)
    proposed, _ = await _user(UserRole.recruiter)
    auto_job = await _job(working_title="Automat od razu")
    shadow_job = await _job()
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        counts = await _apply(
            db,
            [Change("assign", shadow_job, proposed, "recruiter", "")],
            mode="shadow",
            now=now,
        )
        await db.commit()
    assert counts["assigned"] == 1
    assert await _assignment_notices(proposed, shadow_job) == []

    async with AsyncSessionLocal() as db:
        await _apply(
            db,
            [
                Change("assign", auto_job, assigned, "recruiter", ""),
                Change("activate", shadow_job, proposed, "recruiter", ""),
            ],
            mode="auto",
            now=now,
        )
        await db.commit()

    assert await _owner(auto_job) == assigned
    (notice,) = await _assignment_notices(assigned, auto_job)
    assert notice.title == "Nowy request do pracy"
    assert notice.link == f"/jobs/{auto_job}"
    assert notice.message.startswith("Automat od razu · prop-client-")
    (activated,) = await _assignment_notices(proposed, shadow_job)
    assert activated.title == "Nowy request do pracy"


async def test_auto_mode_assigns_without_compass_and_waits_for_stale_compass(
    monkeypatch,
) -> None:
    """Cały przebieg w trybie ``auto``. Urlopy z Compassa włączone, ale
    nieaktualne — automat czeka; wyłączone — przydziela od razu, wpisuje
    prowadzącego i dzwoni. Przebiegi idą w transakcji wycofanej na końcu."""
    from app.services.recruitment_allocation import allocation_lock
    from app.services.request_allocation import run_request_allocation

    category = await _category()
    person, _ = await _user(UserRole.recruiter)
    await _give_category(person, category)
    job_id = await _job(
        competence_category_id=category,
        priority=JobPriority.urgent,
        deadline=date(2000, 1, 1),
    )
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(settings.BUSINESS_TZ)).date().isoformat()

    async def run(db):
        return await run_request_allocation(
            db,
            mode="auto",
            availability_fresh=False,
            available_ids=set(),
            stats={"last_review_date": today},
            now=now,
        )

    async def rows(db):
        return [
            (r.user_id, r.source, r.state)
            for r in (
                await db.scalars(
                    select(JobWorkAssignment)
                    .where(JobWorkAssignment.job_id == job_id)
                    .execution_options(populate_existing=True)
                )
            ).all()
        ]

    async with AsyncSessionLocal() as db:
        try:
            await allocation_lock(db)
            monkeypatch.setattr(settings, "COMPASS_AVAILABILITY_ENABLED", True)
            stats = await run(db)
            assert stats["leave_blocks_auto"] is True
            assert await rows(db) == []

            monkeypatch.setattr(settings, "COMPASS_AVAILABILITY_ENABLED", False)
            stats = await run(db)
            assert stats["leave_blocks_auto"] is False
            assert await rows(db) == [(person, "auto", "active")]
            job = await db.get(Job, job_id, populate_existing=True)
            assert job.recruiter_id == person
            notice = await db.scalar(
                select(Notification).where(
                    Notification.user_id == person,
                    Notification.notification_type
                    == NotificationType.request_assignment_changed,
                    Notification.related_entity_type == "job",
                    Notification.related_entity_id == job_id,
                )
            )
            assert notice is not None
            assert notice.title == "Nowy request do pracy"
        finally:
            await db.rollback()
