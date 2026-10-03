"""Rola „Rekruter” — loader i klauzule SQL muszą dawać ten sam zbiór.

Decyzja Artura 02.10.2026: przy rekrutacji pracują prowadzący
(``jobs.recruiter_id``), osoby z AKTYWNYM przypisaniem i ręcznie dopisani
współpracownicy. Lista ``/jobs`` filtruje klauzulami SQL
(``jobs_worked_by_clause``, ``jobs_nobody_working_clause``), a wiersz listy,
panel rekrutacji i pulpit pokazują ludzi loaderem (``recruiters_for_jobs``).
Rozjazd tych dwóch = filtr „Rekruter: X” zwraca rekrutację, w której X nie
widać — dlatego test porównuje je osoba po osobie, na każdej gałęzi reguły.

Baza testowa jest wspólna i nieczyszczona: każde zapytanie jest zawężone do
rekrutacji założonych przez test.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select
from sqlalchemy.dialects import postgresql

from app.models.user import UserRole

# ── Bez bazy ─────────────────────────────────────────────────────────────────


def _sql(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_working_leaves_out_proposals() -> None:
    from app.services.job_team import TeamPerson, working

    owner = TeamPerson(1, "Anna", "recruiter", "owner")
    proposal = TeamPerson(2, "Jan", "recruiter", "assignment", proposed=True)

    assert working([owner, proposal]) == [owner]


def test_clauses_count_active_assignments_and_manual_collaborators() -> None:
    from app.services.job_team import (
        jobs_nobody_working_clause,
        jobs_worked_by_clause,
    )

    for clause in (jobs_worked_by_clause([1]), jobs_nobody_working_clause()):
        sql = _sql(clause)
        # Propozycja automatu (`proposed`) to jeszcze nie praca, a wiersz
        # `owner` jest lustrem prowadzącego — żaden nie liczy się osobno.
        assert "job_work_assignments.state = 'active'" in sql, sql
        assert "job_work_assignments.source != 'owner'" in sql, sql
        assert "job_collaborators.source = 'manual'" in sql, sql
        assert "jobs.recruiter_id" in sql, sql


def test_old_names_stay_importable_from_the_jobs_router() -> None:
    """Cztery moduły i pięć plików testów importuje je z ``app.api.jobs``."""
    from app.api import jobs
    from app.services import job_team

    assert jobs._live_work_assignment_job_ids is job_team.working_assignment_job_ids
    assert jobs._owner_is_working_clause is job_team.owner_is_working_clause
    assert jobs._manual_collaborator_job_ids is job_team.manual_collaborator_job_ids
    assert jobs.jobs_worked_by_clause is job_team.jobs_worked_by_clause
    assert jobs.jobs_nobody_working_clause is job_team.jobs_nobody_working_clause


def test_mine_clause_counts_manual_collaborators_only() -> None:
    """„Moje” bez wierszy ``auto_cc`` — cała kategoria to nie „moje”."""
    from app.api.jobs import jobs_mine_clause, jobs_my_category_clause

    user = SimpleNamespace(id=7, roles=["recruiter"], role="recruiter")
    mine = _sql(jobs_mine_clause(user))
    assert "job_collaborators.source = 'manual'" in mine, mine
    assert "job_collaborators.removed_from_auto_cc IS false" in mine, mine
    assert "job_work_assignments.state = 'active'" in mine, mine

    category = _sql(jobs_my_category_clause(user))
    assert "user_competence_categories.user_id = 7" in category, category
    assert "jobs.status != 'closed'" in category, category
    # Kategoria GŁÓWNA rekrutacji — dodatkowe (`job_secondary_ccs`) nie.
    assert "jobs.competence_category_id IN" in category, category
    assert "job_secondary" not in category, category


# ── Parzystość loader ⇔ SQL (baza) ───────────────────────────────────────────


async def assert_team_parity(db, job_ids: list[int], user_ids: list[int]) -> dict:
    """Dla każdej osoby: filtr „Rekruter” zwraca rekrutację ⇔ loader ją pokazuje.

    ``db`` potrzebuje tylko ``execute`` i ``scalars``. Zwraca zbiór pracujących
    per rekrutacja — wołający porównuje go jeszcze z oczekiwaniem wpisanym
    wprost, żeby obie strony nie mogły mylić się tak samo.
    """
    from app.models.job import Job
    from app.services.job_team import (
        jobs_nobody_working_clause,
        jobs_worked_by_clause,
        recruiters_for_jobs,
        working,
    )

    people = await recruiters_for_jobs(db, job_ids)
    assert set(people) == set(job_ids)
    working_by_job = {
        job_id: {person.user_id for person in working(people[job_id])}
        for job_id in job_ids
    }
    for user_id in user_ids:
        listed = set(
            (
                await db.scalars(
                    select(Job.id).where(
                        Job.id.in_(job_ids), jobs_worked_by_clause([user_id])
                    )
                )
            ).all()
        )
        shown = {job_id for job_id, ids in working_by_job.items() if user_id in ids}
        assert listed == shown, f"osoba {user_id}: SQL {listed} ≠ loader {shown}"
    nobody = set(
        (
            await db.scalars(
                select(Job.id).where(Job.id.in_(job_ids), jobs_nobody_working_clause())
            )
        ).all()
    )
    empty = {job_id for job_id, ids in working_by_job.items() if not ids}
    assert nobody == empty, f"„Bez rekrutera”: SQL {nobody} ≠ loader {empty}"
    return working_by_job


async def _seed_world() -> dict:
    """Rekrutacje na każdą gałąź reguły + jedna z całym zespołem naraz."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
    from app.models.job_work_assignment import JobWorkAssignment
    from app.models.user import User

    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)

    async with AsyncSessionLocal() as db:
        client = Client(name=f"JobTeam-{tag}")
        db.add(client)

        def person(label: str, role: UserRole, *, active: bool = True) -> User:
            user = User(
                email=f"job-team-{label}-{tag}@example.com",
                name=f"JobTeam {label} {tag}",
                role=role,
                roles=[role.value],
                is_active=active,
                profile_completed=True,
            )
            db.add(user)
            return user

        people = {
            "owner": person("owner", UserRole.recruiter),
            "gone": person("gone", UserRole.recruiter, active=False),
            "released": person("released", UserRole.recruiter),
            "manual": person("manual", UserRole.recruiter),
            "auto": person("auto", UserRole.recruiter),
            "previous": person("previous", UserRole.recruiter),
            "proposed": person("proposed", UserRole.recruiter),
            "collab": person("collab", UserRole.recruiter),
            "category": person("category", UserRole.recruiter),
            "dead_collab": person("dead-collab", UserRole.recruiter, active=False),
            "assigner": person("assigner", UserRole.head_of_recruitment),
        }
        await db.flush()
        u = {label: user.id for label, user in people.items()}

        def job(label: str, **fields) -> Job:
            row = Job(
                title=f"JobTeam-{label}-{tag}",
                status=JobStatus.published,
                client_id=client.id,
                **fields,
            )
            db.add(row)
            return row

        jobs = {
            "owner": job("owner", recruiter_id=u["owner"]),
            "inactive_owner": job("inactive-owner", recruiter_id=u["gone"]),
            # Prowadzący zdjęty ręcznie w BIEŻĄCYM stanie requestu.
            "released_owner": job("released-owner", recruiter_id=u["released"]),
            "released_after_change": job(
                "released-after-change",
                recruiter_id=u["released"],
                work_state_changed_at=now - timedelta(days=2),
            ),
            # Zdjęty PRZED zmianą stanu — blokada już nie obowiązuje.
            "released_before_change": job(
                "released-before-change",
                recruiter_id=u["released"],
                work_state_changed_at=now - timedelta(days=1),
            ),
            "manual_row": job("manual-row"),
            "auto_row": job("auto-row"),
            "stale_owner_row": job("stale-owner-row"),
            "proposed_only": job("proposed-only"),
            "manual_collab": job("manual-collab"),
            "auto_cc": job("auto-cc"),
            "dead_collab": job("dead-collab"),
            "removed_collab": job("removed-collab"),
            "inactive_assignment": job("inactive-assignment"),
            "released_assignment": job("released-assignment"),
            "team": job("team", recruiter_id=u["owner"]),
        }
        await db.flush()
        j = {label: row.id for label, row in jobs.items()}

        def assignment(job_label, user_label, *, source, state, role="recruiter", **kw):
            db.add(
                JobWorkAssignment(
                    job_id=j[job_label],
                    user_id=u[user_label],
                    role=role,
                    source=source,
                    state=state,
                    **kw,
                )
            )

        def collaborator(job_label, user_label, *, source="manual", removed=False):
            db.add(
                JobCollaborator(
                    job_id=j[job_label],
                    user_id=u[user_label],
                    source=JobCollaboratorSource(source),
                    removed_from_auto_cc=removed,
                )
            )

        manual_release = {
            "source": "owner",
            "state": "released",
            "release_reason": "manual",
        }
        assignment("released_owner", "released", released_at=now, **manual_release)
        assignment(
            "released_after_change",
            "released",
            released_at=now - timedelta(days=1),
            **manual_release,
        )
        assignment(
            "released_before_change",
            "released",
            released_at=now - timedelta(days=2),
            **manual_release,
        )
        assignment(
            "manual_row",
            "manual",
            source="manual",
            state="active",
            assigned_by=u["assigner"],
        )
        assignment("auto_row", "auto", source="auto", state="active")
        # Lustro prowadzącego po zmianie prowadzącego — żyje do przebiegu automatu.
        assignment("stale_owner_row", "previous", source="owner", state="active")
        assignment("proposed_only", "proposed", source="auto", state="proposed")
        assignment("inactive_assignment", "gone", source="manual", state="active")
        assignment(
            "released_assignment",
            "manual",
            source="auto",
            state="released",
            release_reason="unavailable",
            released_at=now,
        )
        collaborator("manual_collab", "collab")
        collaborator("auto_cc", "category", source="auto_cc")
        collaborator("dead_collab", "dead_collab")
        collaborator("removed_collab", "collab", removed=True)

        # Cały zespół przy jednej rekrutacji; każda osoba ma wystąpić RAZ.
        assignment(
            "team",
            "owner",
            source="manual",
            state="active",
            assigned_at=now - timedelta(hours=3),
            assigned_by=u["assigner"],
        )
        assignment(
            "team",
            "manual",
            source="manual",
            state="active",
            assigned_at=now - timedelta(hours=2),
        )
        assignment(
            "team",
            "auto",
            source="auto",
            state="active",
            assigned_at=now - timedelta(hours=1),
        )
        assignment(
            "team",
            "proposed",
            source="auto",
            state="proposed",
            assigned_at=now - timedelta(minutes=30),
        )
        collaborator("team", "manual")
        collaborator("team", "collab")
        collaborator("team", "category", source="auto_cc")
        await db.commit()
        return {
            "users": u,
            "jobs": j,
            "names": {label: user.name for label, user in people.items()},
        }


async def _cleanup(job_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        # Przypisania i współpracownicy schodzą kaskadą z rekrutacją.
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_sql_filters_and_loader_agree_on_every_branch() -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.job_team import jobs_worked_by_clause, recruiters_for_jobs

    world = await _seed_world()
    u, j, names = world["users"], world["jobs"], world["names"]
    job_ids = list(j.values())
    try:
        async with AsyncSessionLocal() as db:
            working_by_job = await assert_team_parity(db, job_ids, list(u.values()))

            # Oczekiwanie wpisane wprost — parzystość nie wystarcza, gdyby
            # obie strony myliły się tak samo.
            assert working_by_job == {
                j["owner"]: {u["owner"]},
                j["inactive_owner"]: set(),
                j["released_owner"]: set(),
                j["released_after_change"]: set(),
                j["released_before_change"]: {u["released"]},
                j["manual_row"]: {u["manual"]},
                j["auto_row"]: {u["auto"]},
                j["stale_owner_row"]: set(),
                j["proposed_only"]: set(),
                j["manual_collab"]: {u["collab"]},
                j["auto_cc"]: set(),
                j["dead_collab"]: set(),
                j["removed_collab"]: set(),
                j["inactive_assignment"]: set(),
                j["released_assignment"]: set(),
                j["team"]: {u["owner"], u["manual"], u["auto"], u["collab"]},
            }

            # Kilka osób naraz w filtrze = LUB.
            both = set(
                (
                    await db.scalars(
                        select(Job.id).where(
                            Job.id.in_(job_ids),
                            jobs_worked_by_clause([u["auto"], u["collab"]]),
                        )
                    )
                ).all()
            )
            assert both == {j["auto_row"], j["manual_collab"], j["team"]}

            people = await recruiters_for_jobs(db, job_ids)
            # Pusta lista rekrutacji = pusty wynik, bez zapytania.
            assert await recruiters_for_jobs(db, []) == {}

        # Propozycja wraca osobno — widać ją, ale nie jest pracą.
        (proposal,) = people[j["proposed_only"]]
        assert (proposal.user_id, proposal.via, proposal.proposed) == (
            u["proposed"],
            "assignment",
            True,
        )
        # Lustro poprzedniego prowadzącego nie jest ani pracą, ani propozycją.
        assert people[j["stale_owner_row"]] == []

        # Kolejność: prowadzący, przypisania od najstarszego, ręczni
        # współpracownicy, propozycje. Każda osoba raz.
        team = people[j["team"]]
        assert [(p.user_id, p.via, p.proposed) for p in team] == [
            (u["owner"], "owner", False),
            (u["manual"], "assignment", False),
            (u["auto"], "assignment", False),
            (u["collab"], "collaborator", False),
            (u["proposed"], "assignment", True),
        ]
        # Rola pracy jest jedna (0411): także współpracownik bez wiersza
        # przypisania i prowadzący bez własnego wiersza są „rekruterem”.
        assert [p.role for p in team] == ["recruiter"] * 5
        assert team[0].name == names["owner"]
        # Prowadzący z własnym wierszem przypisania niesie, kto go przydzielił.
        assert team[0].assigned_by_name == names["assigner"]
        assert team[1].assigned_by_name is None

        (manual,) = people[j["manual_row"]]
        assert manual.assigned_by_name == names["assigner"]
    finally:
        await _cleanup(job_ids)


# ── Zdjęcie osoby z roli „Rekruter” (baza) ───────────────────────────────────


async def _seed_removal_job(*, owner_row_source: str) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.job_collaborator import JobCollaborator
    from app.models.job_work_assignment import JobWorkAssignment
    from app.models.user import User

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"JobTeamRemove-{tag}")
        recruiter = User(
            email=f"job-team-remove-{tag}@example.com",
            name=f"JobTeam remove {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
            profile_completed=True,
        )
        bystander = User(
            email=f"job-team-bystander-{tag}@example.com",
            name=f"JobTeam bystander {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
            profile_completed=True,
        )
        actor = User(
            email=f"job-team-actor-{tag}@example.com",
            name=f"JobTeam actor {tag}",
            role=UserRole.head_of_recruitment,
            roles=["head_of_recruitment"],
            is_active=True,
            profile_completed=True,
        )
        db.add_all([client, recruiter, bystander, actor])
        await db.flush()
        # Stan domyślny („Do przejrzenia”) — poza pulą automatu przydziału,
        # żeby cudze testy na wspólnej bazie nie dobierały tu ludzi.
        job = Job(
            title=f"JobTeamRemove-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=recruiter.id,
        )
        db.add(job)
        await db.flush()
        db.add_all(
            [
                JobWorkAssignment(
                    job_id=job.id,
                    user_id=recruiter.id,
                    role="recruiter",
                    source=owner_row_source,
                    state="active",
                ),
                JobWorkAssignment(
                    job_id=job.id,
                    user_id=bystander.id,
                    role="recruiter",
                    source="auto",
                    state="proposed",
                ),
                JobCollaborator(job_id=job.id, user_id=recruiter.id),
            ]
        )
        await db.commit()
        return {
            "job_id": job.id,
            "recruiter_id": recruiter.id,
            "bystander_id": bystander.id,
            "actor_id": actor.id,
        }


async def _remove(job_id: int, user_id: int, actor_id: int) -> bool:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.job_team import remove_recruiter
    from app.services.recruitment_allocation import allocation_lock

    async with AsyncSessionLocal() as db:
        await allocation_lock(db)
        job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        removed = await remove_recruiter(
            db, job=job, user_id=user_id, actor_id=actor_id
        )
        await db.commit()
        return removed


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_row_source", ["auto", "manual", "owner"])
async def test_remove_recruiter_takes_the_person_out_of_all_three_places(
    owner_row_source: str,
) -> None:
    """Prowadzący z aktywnym przypisaniem i ręcznym dopisaniem znika w całości.

    Wariant ``auto`` to prowadzący wpisany przez automat: ``manual_remove``
    czyści wtedy ``recruiter_id`` własnym UPDATE-em, a mimo to wpis w historii
    ma powstać dokładnie raz.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.job import Job
    from app.models.job_collaborator import JobCollaborator
    from app.models.job_work_assignment import JobWorkAssignment
    from app.services.job_team import recruiters_for_jobs

    world = await _seed_removal_job(owner_row_source=owner_row_source)
    job_id, recruiter_id = world["job_id"], world["recruiter_id"]
    try:
        assert await _remove(job_id, recruiter_id, world["actor_id"]) is True

        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            assert job.recruiter_id is None
            rows = {
                row.user_id: row
                for row in (
                    await db.scalars(
                        select(JobWorkAssignment).where(
                            JobWorkAssignment.job_id == job_id
                        )
                    )
                ).all()
            }
            assert rows[recruiter_id].state == "released"
            # Powód `manual` blokuje powrót osoby z automatu w tym stanie.
            assert rows[recruiter_id].release_reason == "manual"
            # Propozycji innej osoby zdjęcie nie rusza — tę się odrzuca.
            assert rows[world["bystander_id"]].state == "proposed"
            assert (
                await db.scalar(
                    select(JobCollaborator.id).where(
                        JobCollaborator.job_id == job_id,
                        JobCollaborator.user_id == recruiter_id,
                    )
                )
            ) is None
            history = (
                await db.execute(
                    select(Activity.action, Activity.user_id, Activity.details).where(
                        Activity.entity_type == "job", Activity.entity_id == job_id
                    )
                )
            ).all()
            released = [row for row in history if row.action == "owner_released"]
            assert len(released) == 1
            assert released[0].user_id == world["actor_id"]
            assert released[0].details == {"previous_owner_id": recruiter_id}
            assert [row.action for row in history].count("collaborator_removed") == 1

            people = (await recruiters_for_jobs(db, [job_id]))[job_id]
            assert [(p.user_id, p.proposed) for p in people] == [
                (world["bystander_id"], True)
            ]

        # Drugie zdjęcie nie ma już czego zdejmować.
        assert await _remove(job_id, recruiter_id, world["actor_id"]) is False
        # Osoby z samą propozycją zdjęcie nie dotyczy.
        assert await _remove(job_id, world["bystander_id"], world["actor_id"]) is False
    finally:
        await _cleanup([job_id])


async def _seed_owner_only_job(*, role: UserRole, in_pool: bool) -> dict:
    """Rekrutacja z samym prowadzącym — bez wiersza przypisania (stan sprzed
    włączenia automatu albo przed jego najbliższym przebiegiem)."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.user import User

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"JobTeamOwnerOnly-{tag}")
        owner = User(
            email=f"job-team-owner-only-{tag}@example.com",
            name=f"JobTeam owner only {tag}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        actor = User(
            email=f"job-team-owner-only-actor-{tag}@example.com",
            name=f"JobTeam owner only actor {tag}",
            role=UserRole.head_of_recruitment,
            roles=["head_of_recruitment"],
            is_active=True,
            profile_completed=True,
        )
        db.add_all([client, owner, actor])
        await db.flush()
        job = Job(
            title=f"JobTeamOwnerOnly-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=owner.id,
            **({"work_state": "searching"} if in_pool else {}),
        )
        db.add(job)
        await db.commit()
        return {"job_id": job.id, "owner_id": owner.id, "actor_id": actor.id}


@pytest.mark.asyncio
async def test_removing_an_owner_without_an_assignment_row_is_remembered() -> None:
    """Zdjęty prowadzący nie wraca jako propozycja automatu.

    Do tej poprawki ślad „zdjęty ręcznie” powstawał tylko, gdy osoba miała
    aktywny wiersz przypisania. Prowadzący sprzed włączenia automatu (albo
    wpisany między przebiegami) go nie miał, więc planer mógł zaproponować tę
    samą osobę do tego samego requestu zaraz po zdjęciu.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.job_work_assignment import JobWorkAssignment
    from app.services.request_allocation import _blocked

    world = await _seed_owner_only_job(role=UserRole.recruiter, in_pool=True)
    job_id, owner_id = world["job_id"], world["owner_id"]
    try:
        assert await _remove(job_id, owner_id, world["actor_id"]) is True
        async with AsyncSessionLocal() as db:
            rows = (
                await db.scalars(
                    select(JobWorkAssignment).where(JobWorkAssignment.job_id == job_id)
                )
            ).all()
            assert [(r.user_id, r.role, r.state, r.release_reason) for r in rows] == [
                (owner_id, "recruiter", "released", "manual")
            ]
            assert rows[0].released_at is not None
            assert (job_id, owner_id) in await _blocked(db)
    finally:
        await _cleanup([job_id])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("role", "in_pool"),
    [
        # Poza pulą automat nikogo nie dobiera — nie ma czego pamiętać.
        (UserRole.recruiter, False),
        # Delivery Lead jako prowadzący nie jest osobą, którą planer proponuje.
        (UserRole.delivery_lead, True),
    ],
)
async def test_owner_removal_leaves_no_row_where_the_planner_never_looks(
    role: UserRole, in_pool: bool
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.job_work_assignment import JobWorkAssignment

    world = await _seed_owner_only_job(role=role, in_pool=in_pool)
    job_id = world["job_id"]
    try:
        assert await _remove(job_id, world["owner_id"], world["actor_id"]) is True
        async with AsyncSessionLocal() as db:
            assert (await db.get(Job, job_id)).recruiter_id is None
            assert (
                await db.scalars(
                    select(JobWorkAssignment.id).where(
                        JobWorkAssignment.job_id == job_id
                    )
                )
            ).all() == []
    finally:
        await _cleanup([job_id])


@pytest.mark.asyncio
async def test_reassigning_a_removed_owner_makes_them_a_recruiter_again() -> None:
    """Każda droga, którą człowiek wpisuje prowadzącego, znosi ślad zdjęcia.

    `/owner` i `/claim` robią to przez synchronizację przypisań; przypisanie
    z planu priorytetów wołało samo `assign_operator` i zostawiało osobę
    prowadzącą, której reguła zespołu nie liczyła jako Rekrutera.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.recruitment_priority import (
        PriorityChannel,
        RecruitmentPriorityAssignment,
        RecruitmentPriorityDemand,
    )
    from app.models.user import User
    from app.services.job_team import recruiters_for_jobs
    from app.services.recruitment_allocation import allocation_lock, assign_operator

    world = await _seed_owner_only_job(role=UserRole.recruiter, in_pool=True)
    job_id, owner_id = world["job_id"], world["owner_id"]
    try:
        assert await _remove(job_id, owner_id, world["actor_id"]) is True
        async with AsyncSessionLocal() as db:
            await allocation_lock(db)
            job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
            await assign_operator(
                db,
                job=job,
                assignee=await db.get(User, owner_id),
                channel=PriorityChannel.linkedin,
                actor_user_id=world["actor_id"],
                source="delivery_lead",
                as_owner=False,
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert (await db.get(Job, job_id)).recruiter_id == owner_id
            people = (await recruiters_for_jobs(db, [job_id]))[job_id]
            assert [p.user_id for p in people if not p.proposed] == [owner_id]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(RecruitmentPriorityAssignment).where(
                    RecruitmentPriorityAssignment.job_id == job_id
                )
            )
            await db.execute(
                delete(RecruitmentPriorityDemand).where(
                    RecruitmentPriorityDemand.job_id == job_id
                )
            )
            await db.commit()
        await _cleanup([job_id])


# ── Członkostwo rekrutacji zna aktywne przypisanie (baza) ────────────────────


@pytest.mark.asyncio
async def test_active_assignment_makes_a_job_member_and_a_proposal_does_not() -> None:
    """Zaakceptowany sourcer dostaje powiadomienia rekrutacji; proponowany nie."""
    from app.core.database import AsyncSessionLocal
    from app.models.job_work_assignment import JobWorkAssignment
    from app.models.user import User
    from app.services.job_membership import is_member_of_job, list_job_member_ids

    world = await _seed_removal_job(owner_row_source="owner")
    job_id, sourcer_id = world["job_id"], world["bystander_id"]
    try:
        async with AsyncSessionLocal() as db:
            sourcer = await db.get(User, sourcer_id)
            # Na razie tylko propozycja automatu.
            assert not await is_member_of_job(db, sourcer, job_id)
            assert sourcer_id not in await list_job_member_ids(db, job_id)

            row = await db.scalar(
                select(JobWorkAssignment).where(
                    JobWorkAssignment.job_id == job_id,
                    JobWorkAssignment.user_id == sourcer_id,
                )
            )
            row.state = "active"
            row.source = "manual"
            await db.commit()

        async with AsyncSessionLocal() as db:
            sourcer = await db.get(User, sourcer_id)
            assert await is_member_of_job(db, sourcer, job_id)
            members = await list_job_member_ids(db, job_id)
            assert sourcer_id in members
            assert world["recruiter_id"] in members
    finally:
        await _cleanup([job_id])


@pytest.mark.asyncio
async def test_losing_recruitment_access_takes_the_person_off_the_team() -> None:
    """Zmiana roli na Finanse zdejmuje osobę także z przypisań do requestów.

    Sprzątanie po zmianie roli czyściło prowadzącego i współpracownika, ale
    aktywne przypisanie zostawało — a od 02.10.2026 ono też daje rolę
    „Rekruter”, więc osoba bez dostępu do rekrutacji stała dalej na liście
    i liczyła się w obłożeniu.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.job_work_assignment import JobWorkAssignment
    from app.services.finance_role_cleanup import clear_recruitment_access_for_finance
    from app.services.job_team import recruiters_for_jobs

    world = await _seed_removal_job(owner_row_source="manual")
    job_id = world["job_id"]
    try:
        async with AsyncSessionLocal() as db:
            for user_id in (world["recruiter_id"], world["bystander_id"]):
                await clear_recruitment_access_for_finance(db, user_id=user_id)
            await db.commit()

        async with AsyncSessionLocal() as db:
            team = await recruiters_for_jobs(db, [job_id])
            assert team.get(job_id, []) == []
            rows = (
                await db.execute(
                    select(
                        JobWorkAssignment.user_id,
                        JobWorkAssignment.state,
                        JobWorkAssignment.release_reason,
                    ).where(JobWorkAssignment.job_id == job_id)
                )
            ).all()
        assert {tuple(row) for row in rows} == {
            (world["recruiter_id"], "released", "excluded"),
            # Zwolniona propozycja niesie przedrostek — nie jest zmianą obsady.
            (world["bystander_id"], "released", "proposal:excluded"),
        }
    finally:
        await _cleanup([job_id])
