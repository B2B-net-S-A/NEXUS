"""Lista ``/jobs`` po decyzjach z 02.10.2026: rola „Rekruter”, priorytet
w trzech poziomach, data otwarcia i zakres „Moja kategoria”.

Rejestr jest wspólny dla całej bazy testowej, więc listy zawężamy unikalnym
tokenem w tytule (``q=``) albo własnym klientem, a liczniki porównujemy
z ``total`` listy z tym samym filtrem (oba są globalne).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.dialects import postgresql

from app.models.user import UserRole
from tests._jarvis_helpers import make_user

# ── Bez bazy ─────────────────────────────────────────────────────────────────


def _sql(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_priority_levels_cover_every_column_value() -> None:
    """Trzy poziomy nad czterema wartościami kolumny — każda wartość należy do
    dokładnie jednego poziomu, więc filtr po wszystkich trzech to cały rejestr."""
    from app.models.job import JobPriority
    from app.services.job_priority import (
        PRIORITY_LEVELS,
        level_of,
        priorities_for_levels,
        priority_rank_expr,
    )

    assert PRIORITY_LEVELS == ("p1", "p2", "accepting")
    assert {p.value: level_of(p) for p in JobPriority} == {
        "urgent": "p1",
        # „high” sprzed trzech poziomów to dziś też P1.
        "high": "p1",
        "medium": "p2",
        "low": "accepting",
    }
    assert priorities_for_levels(["p1", "p1"]) == [JobPriority.urgent, JobPriority.high]
    assert priorities_for_levels(["accepting", "p2"]) == [
        JobPriority.low,
        JobPriority.medium,
    ]
    assert set(priorities_for_levels(PRIORITY_LEVELS)) == set(JobPriority)
    # Pierwszy klucz sortowania „Wymaga uwagi”: P1 przed resztą.
    assert _sql(priority_rank_expr()) == (
        "CASE WHEN (jobs.priority IN ('urgent', 'high')) THEN 0 ELSE 1 END"
    )


def test_opened_window_counts_warsaw_days() -> None:
    """Obie daty włącznie, doba w kalendarzu firmy — nie w UTC."""
    from app.api.jobs import jobs_opened_clauses

    opened = "coalesce(jobs.opened_at, jobs.created_at)"
    # Zima: Warszawa = UTC+1. Górna granica to północ NASTĘPNEGO dnia.
    assert [
        _sql(c) for c in jobs_opened_clauses(date(2026, 3, 10), date(2026, 3, 10))
    ] == [
        f"{opened} >= '2026-03-10 00:00:00+01:00'",
        f"{opened} < '2026-03-11 00:00:00+01:00'",
    ]
    # Lato: UTC+2; każda granica działa osobno.
    assert [_sql(c) for c in jobs_opened_clauses(date(2026, 7, 1), None)] == [
        f"{opened} >= '2026-07-01 00:00:00+02:00'"
    ]
    assert [_sql(c) for c in jobs_opened_clauses(None, date(2026, 7, 1))] == [
        f"{opened} < '2026-07-02 00:00:00+02:00'"
    ]
    assert jobs_opened_clauses(None, None) == []


def test_response_carries_the_level_and_the_effective_opening_date() -> None:
    """Pola wyliczane niesie KAŻDA odpowiedź z rekrutacją (lista, szczegóły,
    PATCH); obsadę i flagi uprawnień wypełniają tylko lista i szczegóły."""
    from app.models.job import JobPriority
    from tests.test_job_viewer_projection import _job_response

    created = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    opened = datetime(2026, 8, 20, 9, 30, tzinfo=timezone.utc)

    assert {p.value: _job_response(priority=p).priority_level for p in JobPriority} == {
        "urgent": "p1",
        "high": "p1",
        "medium": "p2",
        "low": "accepting",
    }
    # `opened_at` stempluje tylko import Traffita — bez niego liczy się założenie.
    assert _job_response(created_at=created).opened_effective_at == created
    assert (
        _job_response(created_at=created, opened_at=opened).opened_effective_at
        == opened
    )

    dumped = _job_response(priority=JobPriority.urgent).model_dump()
    assert dumped["priority_level"] == "p1"
    assert dumped["recruiters"] == []
    assert dumped["can_staff"] is None
    assert dumped["can_set_priority"] is None


async def _seed_job(token: str, **fields) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Staffing-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"{token}-{uuid.uuid4().hex[:4]}",
            status=fields.pop("status", JobStatus.published),
            client_id=client.id,
            **fields,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _cleanup(job_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        # Przypisania, współpracownicy i kategorie dodatkowe schodzą kaskadą.
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()


async def _rows(app_client: AsyncClient, headers: dict, query: str) -> dict[int, dict]:
    response = await app_client.get(f"/api/jobs?page_size=100&{query}", headers=headers)
    assert response.status_code == 200, response.text
    return {row["id"]: row for row in response.json()["items"]}


async def _total(app_client: AsyncClient, headers: dict, query: str) -> int:
    response = await app_client.get(f"/api/jobs?page_size=1&{query}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["total"]


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ── Priorytet ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_priority_level_filter_and_row_field(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.models.job import JobPriority

    token = f"Prio{uuid.uuid4().hex[:8]}"
    jobs = {p.value: await _seed_job(token, priority=p) for p in JobPriority}
    try:
        rows = await _rows(app_client, app_auth_headers, f"q={token}")
        assert {job_id: rows[job_id]["priority_level"] for job_id in rows} == {
            jobs["urgent"]: "p1",
            # „high” sprzed trzech poziomów to dziś też P1.
            jobs["high"]: "p1",
            jobs["medium"]: "p2",
            jobs["low"]: "accepting",
        }

        async def ids(query: str) -> set[int]:
            return set(await _rows(app_client, app_auth_headers, f"q={token}&{query}"))

        assert await ids("priority_level=p1") == {jobs["urgent"], jobs["high"]}
        assert await ids("priority_level=p2") == {jobs["medium"]}
        assert await ids("priority_level=accepting") == {jobs["low"]}
        # Kilka poziomów naraz = LUB.
        assert await ids("priority_level=p1&priority_level=accepting") == {
            jobs["urgent"],
            jobs["high"],
            jobs["low"],
        }

        unknown = await app_client.get(
            "/api/jobs?priority_level=pilne", headers=app_auth_headers
        )
        assert unknown.status_code == 422, unknown.text
        assert "pilne" in unknown.text
    finally:
        await _cleanup(list(jobs.values()))


# ── Data otwarcia ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_opened_range_counts_warsaw_days_and_falls_back_to_created_at(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    token = f"Open{uuid.uuid4().hex[:8]}"

    def utc(*parts: int) -> datetime:
        return datetime(*parts, tzinfo=timezone.utc)

    # 10 marca 2026 — czas zimowy, Warszawa = UTC+1. Granice doby liczone
    # w UTC dałyby odwrotny wynik dla pierwszej i trzeciej rekrutacji.
    early = await _seed_job(token, opened_at=utc(2026, 3, 9, 23, 30))
    late = await _seed_job(token, opened_at=utc(2026, 3, 10, 22, 59))
    next_day = await _seed_job(token, opened_at=utc(2026, 3, 10, 23, 0))
    # Rekrutacja założona w NEXUSIE nie ma `opened_at` — liczy się `created_at`.
    fallback = await _seed_job(token, created_at=utc(2026, 3, 10, 12, 0))
    seeded = [early, late, next_day, fallback]
    try:

        async def ids(query: str) -> set[int]:
            return set(await _rows(app_client, app_auth_headers, f"q={token}&{query}"))

        assert await ids("opened_from=2026-03-10&opened_to=2026-03-10") == {
            early,
            late,
            fallback,
        }
        assert await ids("opened_from=2026-03-11") == {next_day}
        assert await ids("opened_to=2026-03-10") == {early, late, fallback}
        assert await ids("opened_to=2026-03-09") == set()

        rows = await _rows(app_client, app_auth_headers, f"q={token}")
        assert _instant(rows[early]["opened_effective_at"]) == utc(2026, 3, 9, 23, 30)
        assert rows[fallback]["opened_at"] is None
        assert _instant(rows[fallback]["opened_effective_at"]) == utc(
            2026, 3, 10, 12, 0
        )

        reversed_range = await app_client.get(
            "/api/jobs?opened_from=2026-03-11&opened_to=2026-03-10",
            headers=app_auth_headers,
        )
        assert reversed_range.status_code == 422, reversed_range.text
        assert "Data otwarcia" in reversed_range.text

        out_of_bounds = await app_client.get(
            "/api/jobs?opened_from=1800-01-01", headers=app_auth_headers
        )
        assert out_of_bounds.status_code == 422, out_of_bounds.text
    finally:
        await _cleanup(seeded)


# ── „Moja kategoria” ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_my_category_scope_and_its_counter(app_client: AsyncClient) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.cc_feedback import JobSecondaryCc
    from app.models.competence_category import (
        CompetenceCategory,
        UserCompetenceCategory,
    )
    from app.models.job import JobStatus
    from app.models.user import User

    user_id, headers = await make_user(UserRole.recruiter)
    _, stranger_headers = await make_user(UserRole.recruiter)
    token = f"MyCat{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        categories = dict(
            (
                await db.execute(
                    select(CompetenceCategory.slug, CompetenceCategory.id).where(
                        CompetenceCategory.slug.in_(
                            ["software_development", "security_quality"]
                        )
                    )
                )
            ).all()
        )
        dev, qa = categories["software_development"], categories["security_quality"]
        # Osoba testowa ma kategorię, ale nie może dostawać requestów z automatu
        # w cudzych testach na wspólnej bazie.
        await db.execute(
            update(User).where(User.id == user_id).values(allocation_excluded=True)
        )
        db.add(
            UserCompetenceCategory(
                user_id=user_id,
                competence_category_id=dev,
                is_primary=True,
                priority=1,
            )
        )
        await db.commit()

    mine = await _seed_job(token, competence_category_id=dev)
    draft = await _seed_job(token, competence_category_id=dev, status=JobStatus.draft)
    closed = await _seed_job(token, competence_category_id=dev, status=JobStatus.closed)
    other = await _seed_job(token, competence_category_id=qa)
    uncategorised = await _seed_job(token)
    # Moja kategoria tylko jako DODATKOWA rekrutacji — nie liczy się.
    secondary = await _seed_job(token, competence_category_id=qa)
    seeded = [mine, draft, closed, other, uncategorised, secondary]
    async with AsyncSessionLocal() as db:
        db.add(JobSecondaryCc(job_id=secondary, competence_category_id=dev))
        await db.commit()
    try:
        scope = f"q={token}&my_category=true"
        assert set(await _rows(app_client, headers, scope)) == {mine, draft}

        counts = await app_client.get("/api/jobs/quick-counts", headers=headers)
        assert counts.status_code == 200, counts.text
        # Licznik zakresu == lista z tym samym filtrem (oba globalne).
        assert counts.json()["my_category"] == await _total(
            app_client, headers, "my_category=true"
        )
        assert counts.json()["my_category"] >= 2

        # Osoba bez kategorii: pusty zakres (nigdy cały rejestr) i brak licznika.
        assert await _total(app_client, stranger_headers, "my_category=true") == 0
        stranger_counts = await app_client.get(
            "/api/jobs/quick-counts", headers=stranger_headers
        )
        assert stranger_counts.status_code == 200, stranger_counts.text
        assert stranger_counts.json()["my_category"] is None

        # Kategoria 2. priorytetu też jest „moja”.
        async with AsyncSessionLocal() as db:
            db.add(
                UserCompetenceCategory(
                    user_id=user_id,
                    competence_category_id=qa,
                    is_primary=False,
                    priority=2,
                )
            )
            await db.commit()
        assert set(await _rows(app_client, headers, scope)) == {
            mine,
            draft,
            other,
            secondary,
        }
    finally:
        await _cleanup(seeded)
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(UserCompetenceCategory).where(
                    UserCompetenceCategory.user_id == user_id
                )
            )
            await db.commit()


# ── Rola „Rekruter” w wierszu ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rows_and_detail_carry_the_recruiter_role(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
    from app.models.job_work_assignment import JobWorkAssignment

    owner_id, _ = await make_user(UserRole.recruiter)
    sourcer_id, _ = await make_user(UserRole.sourcer)
    proposed_id, _ = await make_user(UserRole.recruiter)
    category_id, _ = await make_user(UserRole.recruiter)
    token = f"Team{uuid.uuid4().hex[:8]}"
    staffed = await _seed_job(token, recruiter_id=owner_id)
    proposal_only = await _seed_job(token)
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobCollaborator(job_id=staffed, user_id=sourcer_id),
                JobCollaborator(
                    job_id=staffed,
                    user_id=category_id,
                    source=JobCollaboratorSource.auto_cc,
                ),
                JobWorkAssignment(
                    job_id=staffed,
                    user_id=proposed_id,
                    role="recruiter",
                    source="auto",
                    state="proposed",
                ),
                JobWorkAssignment(
                    job_id=proposal_only,
                    user_id=proposed_id,
                    role="sourcer",
                    source="auto",
                    state="proposed",
                ),
            ]
        )
        await db.commit()
    try:
        rows = await _rows(app_client, app_auth_headers, f"q={token}")
        recruiters = rows[staffed]["recruiters"]
        assert [
            (r["user_id"], r["role"], r["via"], r["proposed"]) for r in recruiters
        ] == [
            (owner_id, "recruiter", "owner", False),
            (sourcer_id, "sourcer", "collaborator", False),
            # Propozycja automatu jest widoczna, ale to jeszcze nie praca.
            (proposed_id, "recruiter", "assignment", True),
        ]
        assert set(recruiters[0]) == {
            "user_id",
            "name",
            "role",
            "via",
            "proposed",
            "assigned_by_name",
        }
        assert [
            (r["user_id"], r["role"], r["proposed"])
            for r in rows[proposal_only]["recruiters"]
        ] == [(proposed_id, "sourcer", True)]

        detail = await app_client.get(f"/api/jobs/{staffed}", headers=app_auth_headers)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["recruiters"] == recruiters
        assert body["priority_level"] == "p2"
        assert body["opened_at"] is None
        assert body["opened_effective_at"] == body["created_at"]

        async def ids(query: str) -> set[int]:
            return set(await _rows(app_client, app_auth_headers, f"q={token}&{query}"))

        # Filtry liczą tą samą regułą co wiersz.
        assert await ids(f"worked_by={owner_id}") == {staffed}
        assert await ids(f"worked_by={sourcer_id}") == {staffed}
        assert await ids(f"worked_by={proposed_id}") == set()
        assert await ids(f"worked_by={category_id}") == set()
        assert await ids("nobody_working=true") == {proposal_only}
        assert await ids("nobody_working=false") == {staffed}
    finally:
        await _cleanup([staffed, proposal_only])


# ── Sortowanie „Wymaga uwagi” ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_attention_sort_puts_p1_first(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobPriority
    from tests.test_jobs_list_needs_action import _seed

    # „Screening” = karta po stronie rekrutera (liczy się do „wymaga ruchu”).
    busy = await _seed(cards=[("Screening", 0), ("Screening", 0)])
    urgent = await _seed(cards=[])
    high = await _seed(cards=[("Screening", 0)])
    accepting = await _seed(
        cards=[("Screening", 0), ("Screening", 0), ("Screening", 0)]
    )
    async with AsyncSessionLocal() as db:
        for world, priority in (
            (urgent, JobPriority.urgent),
            (high, JobPriority.high),
            (accepting, JobPriority.low),
        ):
            await db.execute(
                update(Job).where(Job.id == world["job_id"]).values(priority=priority)
            )
        await db.commit()

    response = await app_client.get(
        "/api/jobs",
        params={
            "client_id": [w["client_id"] for w in (busy, urgent, high, accepting)],
            "sort": "attention",
            "include_stage_counts": "true",
        },
        headers=app_auth_headers,
    )
    assert response.status_code == 200, response.text
    rows = response.json()["items"]
    # P1 na górze (w środku: więcej ruchu wyżej), dopiero potem reszta —
    # bez tej reguły pierwsza byłaby rekrutacja z trzema kartami.
    assert [row["id"] for row in rows] == [
        high["job_id"],
        urgent["job_id"],
        accepting["job_id"],
        busy["job_id"],
    ]
    assert [row["needs_action_count"] for row in rows] == [1, 0, 3, 2]
    assert [row["priority_level"] for row in rows] == ["p1", "p1", "accepting", "p2"]
