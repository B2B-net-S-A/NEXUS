"""Tests for Recruiter Ownership (primary_owner + collaborators + mine filter).

Uses the in-process `rbac_client` fixture pattern (see tests/test_rbac.py) so
the suite runs in CI without a live uvicorn server. Each test seeds its own
users and at least one job to stay order-independent.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.job import Job, JobStatus
from app.models.team_structure import ClientTacAssignment, DeliveryLeadClientAssignment
from app.models.user import User, UserRole


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def ownership_client() -> AsyncClient:
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _seed_user(role: UserRole, prefix: str = "own") -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"{prefix}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!OWN"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Own Test {role.value} {unique}",
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_client() -> int:
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        c = Client(name=f"OwnTestClient-{uuid.uuid4().hex[:6]}")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(
    recruiter_id: int | None = None,
    status: JobStatus = JobStatus.draft,
    *,
    in_pool: bool = False,
) -> int:
    """``in_pool`` = request w puli przydziału: opublikowany, „Szukamy kandydatów”,
    bez championa. Takie rekrutacje test sprząta (``_drop_jobs``)."""
    client_id = await _seed_client()
    async with AsyncSessionLocal() as db:
        j = Job(
            title=f"Ownership-test Job {uuid.uuid4().hex[:6]}",
            status=JobStatus.published if in_pool else status,
            recruiter_id=recruiter_id,
            client_id=client_id,
            **({"work_state": "searching"} if in_pool else {}),
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _drop_jobs(job_ids: list[int]) -> None:
    """Baza testowa jest wspólna: request zostawiony w puli przydziału dostawałby
    ludzi od automatu uruchamianego w innych plikach."""
    from sqlalchemy import delete

    from app.models.job_work_assignment import JobWorkAssignment

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(JobWorkAssignment).where(JobWorkAssignment.job_id.in_(job_ids))
        )
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()


async def _work_rows(job_id: int) -> list[tuple[int, str, str, str, str | None]]:
    """(osoba, stan, źródło, rola, powód zwolnienia) — w kolejności powstania."""
    from app.models.job_work_assignment import JobWorkAssignment

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(JobWorkAssignment)
                .where(JobWorkAssignment.job_id == job_id)
                .order_by(JobWorkAssignment.id)
            )
        ).all()
        return [
            (row.user_id, row.state, row.source, row.role, row.release_reason)
            for row in rows
        ]


async def _job_actions(job_id: int) -> list[str]:
    from app.models.activity import Activity

    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Activity.action).where(
                        Activity.entity_type == "job", Activity.entity_id == job_id
                    )
                )
            ).all()
        )


async def _grant_dl_job_scope(delivery_lead_id: int, job_id: int) -> None:
    """Attach a job to the explicit client–TAC graph visible to one DL."""
    tac_id, _, _ = await _seed_user(UserRole.tac, prefix="own-scope")
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job is not None
        job.tac_id = tac_id
        db.add_all(
            [
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=delivery_lead_id,
                    client_id=job.client_id,
                    is_head=True,
                ),
                ClientTacAssignment(
                    tac_user_id=tac_id,
                    client_id=job.client_id,
                    is_primary=False,
                    is_first_priority_for_tac=False,
                ),
            ]
        )
        await db.commit()


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── Assign owner (Admin + DL only) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_assign_owner_as_dl_succeeds(ownership_client: AsyncClient):
    dl_id, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job()
    await _grant_dl_job_scope(dl_id, job_id)

    headers = await _login(ownership_client, dl_email, dl_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/owner",
        headers=headers,
        json={"user_id": rec_id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recruiter_id"] == rec_id
    assert body["primary_owner"]["id"] == rec_id


@pytest.mark.asyncio
async def test_assign_owner_as_admin_succeeds(ownership_client: AsyncClient):
    _, admin_email, admin_pass = await _seed_user(UserRole.admin)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job()

    headers = await _login(ownership_client, admin_email, admin_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/owner",
        headers=headers,
        json={"user_id": rec_id},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_assign_owner_as_tac_forbidden(ownership_client: AsyncClient):
    _, tac_email, tac_pass = await _seed_user(UserRole.tac)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job()

    headers = await _login(ownership_client, tac_email, tac_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/owner",
        headers=headers,
        json={"user_id": rec_id},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_assign_owner_rejects_read_only_user(ownership_client: AsyncClient):
    dl_id, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    viewer_id, _, _ = await _seed_user(UserRole.user)
    job_id = await _seed_job()
    await _grant_dl_job_scope(dl_id, job_id)

    headers = await _login(ownership_client, dl_email, dl_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/owner",
        headers=headers,
        json={"user_id": viewer_id},
    )
    assert resp.status_code == 409, resp.text


# ── Head of Recruitment i rola „Rekruter” (decyzje 02.10.2026) ───────────────


@pytest.mark.asyncio
async def test_head_of_recruitment_assigns_and_releases_the_owner(
    ownership_client: AsyncClient,
):
    """HoR układa pracę zespołu, więc zmienia rekrutera tam, gdzie Delivery Lead.

    Do 02.10.2026 obie trasy stały za ``DeliveryLeadPlus`` i HoR dostawał 403.
    """
    _, hor_email, hor_pass = await _seed_user(UserRole.head_of_recruitment)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job()

    headers = await _login(ownership_client, hor_email, hor_pass)
    assigned = await ownership_client.post(
        f"/api/jobs/{job_id}/owner", headers=headers, json={"user_id": rec_id}
    )
    assert assigned.status_code == 200, assigned.text
    body = assigned.json()
    assert body["recruiter_id"] == rec_id
    assert body["can_staff"] is True
    assert [
        (p["user_id"], p["role"], p["via"], p["proposed"]) for p in body["recruiters"]
    ] == [(rec_id, "recruiter", "owner", False)]

    released = await ownership_client.delete(
        f"/api/jobs/{job_id}/owner", headers=headers
    )
    assert released.status_code == 200, released.text
    assert released.json()["recruiter_id"] is None
    assert released.json()["primary_owner"] is None
    assert released.json()["recruiters"] == []

    actions = await _job_actions(job_id)
    assert actions.count("owner_assigned") == 1
    # Jeden wpis — zostawia go `remove_recruiter`, trasa nie dopisuje drugiego.
    assert actions.count("owner_released") == 1


@pytest.mark.asyncio
async def test_release_owner_as_tac_forbidden(ownership_client: AsyncClient):
    _, tac_email, tac_pass = await _seed_user(UserRole.tac)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(recruiter_id=rec_id)

    headers = await _login(ownership_client, tac_email, tac_pass)
    resp = await ownership_client.delete(f"/api/jobs/{job_id}/owner", headers=headers)
    assert resp.status_code == 403, resp.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job is not None and job.recruiter_id == rec_id


@pytest.mark.asyncio
async def test_release_owner_without_an_owner_leaves_no_history_entry(
    ownership_client: AsyncClient,
):
    _, admin_email, admin_pass = await _seed_user(UserRole.admin)
    job_id = await _seed_job()

    headers = await _login(ownership_client, admin_email, admin_pass)
    resp = await ownership_client.delete(f"/api/jobs/{job_id}/owner", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["recruiter_id"] is None
    assert "owner_released" not in await _job_actions(job_id)


@pytest.mark.asyncio
async def test_release_owner_takes_the_person_out_of_the_recruiter_role(
    ownership_client: AsyncClient,
):
    """Rekruter bywa w trzech miejscach naraz: ``recruiter_id``, aktywne
    przypisanie i ręczne dopisanie. Zdjęcie czyści wszystkie — do 02.10.2026
    znikało samo ``recruiter_id``, a osoba dalej „pracowała” na liście."""
    from app.models.job_collaborator import JobCollaborator
    from app.models.job_work_assignment import JobWorkAssignment

    _, admin_email, admin_pass = await _seed_user(UserRole.admin)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    other_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=rec_id)
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                JobWorkAssignment(
                    job_id=job_id,
                    user_id=rec_id,
                    role="recruiter",
                    source="manual",
                    state="active",
                ),
                JobCollaborator(job_id=job_id, user_id=rec_id, added_by=rec_id),
                # Druga osoba zostaje — zdjęcie dotyczy wyłącznie rekrutera.
                JobCollaborator(job_id=job_id, user_id=other_id, added_by=rec_id),
            ]
        )
        await db.commit()

    headers = await _login(ownership_client, admin_email, admin_pass)
    before = await ownership_client.get(f"/api/jobs/{job_id}", headers=headers)
    assert before.status_code == 200, before.text
    assert [(p["user_id"], p["via"]) for p in before.json()["recruiters"]] == [
        (rec_id, "owner"),
        (other_id, "collaborator"),
    ]

    resp = await ownership_client.delete(f"/api/jobs/{job_id}/owner", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["recruiter_id"] is None
    assert [(p["user_id"], p["via"]) for p in body["recruiters"]] == [
        (other_id, "collaborator")
    ]
    assert [c["id"] for c in body["collaborators"]] == [other_id]

    assert await _work_rows(job_id) == [
        (rec_id, "released", "manual", "recruiter", "manual")
    ]
    actions = await _job_actions(job_id)
    assert actions.count("owner_released") == 1
    assert actions.count("collaborator_removed") == 1

    # Lista mówi to samo co panel: po zdjęciu nikt z nich nie ma rekrutera.
    listed = await ownership_client.get(
        f"/api/jobs?worked_by={rec_id}&page_size=100", headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert job_id not in {row["id"] for row in listed.json()["items"]}


@pytest.mark.asyncio
async def test_owner_change_in_the_pool_moves_the_work_assignment(
    ownership_client: AsyncClient,
):
    """Zmiana rekrutera X → Y w requeście z puli przydziału: X traci aktywne
    przypisanie (powód ``owner_changed`` — automat może go jeszcze kiedyś
    dobrać), Y dostaje ręczne, więc automat nie dobiera do requestu nikogo."""
    from app.models.job_work_assignment import JobWorkAssignment

    admin_id, admin_email, admin_pass = await _seed_user(UserRole.admin)
    old_id, _, _ = await _seed_user(UserRole.recruiter)
    new_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=old_id, in_pool=True)
    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=old_id,
                role="recruiter",
                source="auto",
                state="active",
            )
        )
        await db.commit()
    try:
        headers = await _login(ownership_client, admin_email, admin_pass)
        resp = await ownership_client.post(
            f"/api/jobs/{job_id}/owner", headers=headers, json={"user_id": new_id}
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["recruiter_id"] == new_id
        # Sourcer bez roli rekrutera pracuje jako sourcer (`work_role_of`).
        assert [(p["user_id"], p["role"], p["via"]) for p in body["recruiters"]] == [
            (new_id, "sourcer", "owner")
        ]
        assert await _work_rows(job_id) == [
            (old_id, "released", "auto", "recruiter", "owner_changed"),
            (new_id, "active", "manual", "sourcer", None),
        ]
        async with AsyncSessionLocal() as db:
            assigned_by = await db.scalar(
                select(JobWorkAssignment.assigned_by).where(
                    JobWorkAssignment.job_id == job_id,
                    JobWorkAssignment.user_id == new_id,
                )
            )
        assert assigned_by == admin_id
    finally:
        await _drop_jobs([job_id])


@pytest.mark.asyncio
async def test_owner_outside_the_pool_gets_no_work_assignment(
    ownership_client: AsyncClient,
):
    """Poza pulą wiersz przypisania nie ma sensu (automat zwalnia go przy
    najbliższym przebiegu) — rekruterem osoba jest przez samo ``recruiter_id``."""
    _, admin_email, admin_pass = await _seed_user(UserRole.admin)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(status=JobStatus.published)  # stan „Do przejrzenia”

    headers = await _login(ownership_client, admin_email, admin_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/owner", headers=headers, json={"user_id": rec_id}
    )
    assert resp.status_code == 200, resp.text
    assert [p["user_id"] for p in resp.json()["recruiters"]] == [rec_id]
    assert await _work_rows(job_id) == []


@pytest.mark.asyncio
async def test_owner_removed_and_assigned_again_in_the_pool_works_again(
    ownership_client: AsyncClient,
):
    """Osoba zdjęta ręcznie w bieżącym stanie requestu nie liczy się jako
    prowadzący, dopóki request nie zmieni stanu. Wpisana ponownie musi znowu
    być Rekruterem — inaczej panel mówiłby „prowadzi X”, a lista „Bez rekrutera”."""
    from app.models.job_work_assignment import JobWorkAssignment

    _, admin_email, admin_pass = await _seed_user(UserRole.admin)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(recruiter_id=rec_id, in_pool=True)
    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=rec_id,
                role="recruiter",
                source="manual",
                state="active",
            )
        )
        await db.commit()
    try:
        headers = await _login(ownership_client, admin_email, admin_pass)
        released = await ownership_client.delete(
            f"/api/jobs/{job_id}/owner", headers=headers
        )
        assert released.status_code == 200, released.text
        assert released.json()["recruiters"] == []

        again = await ownership_client.post(
            f"/api/jobs/{job_id}/owner", headers=headers, json={"user_id": rec_id}
        )
        assert again.status_code == 200, again.text
        assert again.json()["primary_owner"]["id"] == rec_id
        assert [(p["user_id"], p["proposed"]) for p in again.json()["recruiters"]] == [
            (rec_id, False)
        ]
        # Świadome ponowne przypisanie znosi wcześniejsze ręczne zdjęcie
        # (`reassigned`), więc osoba wraca jako prowadzący, nie „obok” niego.
        assert again.json()["recruiters"][0]["via"] == "owner"
        assert await _work_rows(job_id) == [
            (rec_id, "released", "manual", "recruiter", "reassigned"),
            (rec_id, "active", "manual", "recruiter", None),
        ]

        # Rejestr jest wspólny dla całej bazy testowej — zawężamy tytułem.
        for query, expected in (
            ({"worked_by": rec_id}, {job_id}),
            ({"nobody_working": "true"}, set()),
        ):
            listed = await ownership_client.get(
                "/api/jobs",
                headers=headers,
                params={"q": again.json()["title"], "page_size": 100, **query},
            )
            assert listed.status_code == 200, listed.text
            assert {row["id"] for row in listed.json()["items"]} == expected, query
    finally:
        await _drop_jobs([job_id])


@pytest.mark.asyncio
async def test_owner_removed_and_assigned_again_outside_the_pool_works_again(
    ownership_client: AsyncClient,
):
    """Request z championem jest poza pulą, więc ponowne przypisanie nie zakłada
    wiersza pracy. Osoba zdjęta wcześniej ręcznie w tym samym stanie requestu
    musi mimo to wrócić do roli „Rekruter” — do 02.10.2026 zostawała prowadzącą,
    a lista i panel mówiły „Bez rekrutera”, bez żadnej drogi powrotu."""
    from app.models.job_work_assignment import JobWorkAssignment

    _, admin_email, admin_pass = await _seed_user(UserRole.admin)
    rec_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(recruiter_id=rec_id, in_pool=True)
    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=rec_id,
                role="recruiter",
                source="manual",
                state="active",
            )
        )
        await db.commit()
    try:
        headers = await _login(ownership_client, admin_email, admin_pass)
        released = await ownership_client.delete(
            f"/api/jobs/{job_id}/owner", headers=headers
        )
        assert released.status_code == 200, released.text
        # Champion znaleziony: request wychodzi z puli, stan się NIE zmienia,
        # więc ręczne zdjęcie nadal by obowiązywało.
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            job.champion_found_at = _CHAMPION_FOUND
            await db.commit()

        again = await ownership_client.post(
            f"/api/jobs/{job_id}/owner", headers=headers, json={"user_id": rec_id}
        )
        assert again.status_code == 200, again.text
        assert [
            (p["user_id"], p["via"], p["proposed"]) for p in again.json()["recruiters"]
        ] == [(rec_id, "owner", False)]
        assert await _work_rows(job_id) == [
            (rec_id, "released", "manual", "recruiter", "reassigned"),
        ]
        listed = await ownership_client.get(
            "/api/jobs",
            headers=headers,
            params={"q": again.json()["title"], "page_size": 100, "worked_by": rec_id},
        )
        assert listed.status_code == 200, listed.text
        assert {row["id"] for row in listed.json()["items"]} == {job_id}
    finally:
        await _drop_jobs([job_id])


@pytest.mark.asyncio
async def test_recruiter_changed_in_the_edit_window_moves_the_work_assignment(
    ownership_client: AsyncClient,
):
    """Okno edycji zmienia rekrutera PATCH-em. Rola „Rekruter” ma wtedy wyglądać
    jak po `/owner`: poprzednia osoba traci aktywne przypisanie, nowa dostaje
    ręczne (request w puli) — inaczej poprzednia zostawała „Rekruterem” obok."""
    from app.models.job_work_assignment import JobWorkAssignment

    _, admin_email, admin_pass = await _seed_user(UserRole.admin)
    old_id, _, _ = await _seed_user(UserRole.recruiter)
    new_id, _, _ = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(recruiter_id=old_id, in_pool=True)
    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=old_id,
                role="recruiter",
                source="manual",
                state="active",
            )
        )
        await db.commit()
    try:
        headers = await _login(ownership_client, admin_email, admin_pass)
        resp = await ownership_client.patch(
            f"/api/jobs/{job_id}", headers=headers, json={"recruiter_id": new_id}
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["recruiter_id"] == new_id
        assert await _work_rows(job_id) == [
            (old_id, "released", "manual", "recruiter", "owner_changed"),
            (new_id, "active", "manual", "recruiter", None),
        ]
        detail = await ownership_client.get(f"/api/jobs/{job_id}", headers=headers)
        assert detail.status_code == 200, detail.text
        assert [(p["user_id"], p["via"]) for p in detail.json()["recruiters"]] == [
            (new_id, "owner")
        ]

        # Zapis tego samego rekrutera (okno edycji odsyła pole przy każdym
        # zapisie) niczego nie rusza.
        same = await ownership_client.patch(
            f"/api/jobs/{job_id}",
            headers=headers,
            json={"recruiter_id": new_id, "title": resp.json()["title"]},
        )
        assert same.status_code == 200, same.text
        assert await _work_rows(job_id) == [
            (old_id, "released", "manual", "recruiter", "owner_changed"),
            (new_id, "active", "manual", "recruiter", None),
        ]
    finally:
        await _drop_jobs([job_id])


# ── Bez bazy: kiedy zmiana rekrutera rusza przypisania ───────────────────────

# Stała chwila, nie „dziś” — liczy się tylko to, że znacznik championa jest.
_CHAMPION_FOUND = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)


def _compiled(statement) -> str:
    from sqlalchemy.dialects import postgresql

    return str(
        statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def _pool_job(**overrides) -> SimpleNamespace:
    fields = {
        "id": 5,
        "status": JobStatus.published,
        "work_state": "searching",
        "champion_found_at": None,
    }
    return SimpleNamespace(**{**fields, **overrides})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("job_overrides", "roles", "expected_role"),
    [
        ({}, ["recruiter"], "recruiter"),
        ({}, ["sourcer"], "sourcer"),
        # TAC, który bywa sourcerem, pracuje jako rekruter (`work_role_of`).
        ({}, ["tac", "sourcer"], "recruiter"),
        # Poza pulą przydziału wiersz nie powstaje — automat i tak by go zwolnił.
        ({"work_state": "to_review"}, ["recruiter"], None),
        ({"work_state": "client_silent"}, ["recruiter"], None),
        ({"champion_found_at": _CHAMPION_FOUND}, ["recruiter"], None),
        ({"status": JobStatus.draft}, ["recruiter"], None),
        ({"status": JobStatus.closed}, ["recruiter"], None),
        # Delivery Lead albo admin jako prowadzący nie dostaje wiersza pracy —
        # lustro pulpitu „Requesty i obłożenie” (rekruter, sourcer, TAC).
        ({}, ["delivery_lead"], None),
        ({}, ["admin"], None),
    ],
)
async def test_new_owner_gets_a_work_assignment_only_in_the_pool(
    monkeypatch, job_overrides: dict, roles: list[str], expected_role: str | None
):
    from unittest.mock import AsyncMock

    from app.api import jobs as jobs_api

    manual_add = AsyncMock()
    monkeypatch.setattr(jobs_api, "manual_add", manual_add)
    db = AsyncMock()
    owner = User(id=9, role=UserRole(roles[0]), roles=roles, is_active=True)

    await jobs_api._sync_work_assignments_with_owner(
        db,
        job=_pool_job(**job_overrides),
        previous_owner_id=None,
        owner=owner,
        actor_id=1,
    )

    # Nie było poprzedniego rekrutera — nie ma komu zwalniać przypisania.
    if expected_role is None:
        # Poza pulą nie powstaje wiersz pracy; jedyny UPDATE znosi wcześniejsze
        # ręczne zdjęcie nowej osoby (inaczej prowadząca „nie pracowałaby”).
        manual_add.assert_not_awaited()
        db.execute.assert_awaited_once()
        voided = _compiled(db.execute.await_args.args[0])
        assert "release_reason='reassigned'" in voided, voided
        assert "job_work_assignments.user_id = 9" in voided, voided
        assert "job_work_assignments.release_reason = 'manual'" in voided, voided
    else:
        # W puli zdjęcie znosi samo `manual_add` (tu podmienione) — ta sama
        # droga co dodanie osoby z pulpitu.
        manual_add.assert_awaited_once_with(
            db, job_id=5, user_id=9, role=expected_role, actor_id=1
        )
        db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_previous_owner_is_released_only_when_the_owner_changes(monkeypatch):
    from unittest.mock import AsyncMock

    from app.api import jobs as jobs_api

    monkeypatch.setattr(jobs_api, "manual_add", AsyncMock())
    owner = User(id=9, role=UserRole.recruiter, roles=["recruiter"], is_active=True)
    job = _pool_job(work_state="to_review")

    same = AsyncMock()
    await jobs_api._sync_work_assignments_with_owner(
        same, job=job, previous_owner_id=9, owner=owner, actor_id=1
    )
    # Ta sama osoba wpisana ponownie nie traci swojego przypisania — jedyny
    # UPDATE znosi jej wcześniejsze ręczne zdjęcie.
    same.execute.assert_awaited_once()
    assert "state='released'" not in _compiled(same.execute.await_args.args[0])

    changed = AsyncMock()
    await jobs_api._sync_work_assignments_with_owner(
        changed, job=job, previous_owner_id=8, owner=owner, actor_id=1
    )
    assert changed.execute.await_count == 2
    sql = _compiled(changed.execute.await_args_list[0].args[0])
    assert sql.startswith("UPDATE job_work_assignments SET"), sql
    assert "state='released'" in sql, sql
    # Powód inny niż `manual`: poprzedniej osoby nikt nie zdjął, automat może
    # ją jeszcze dobrać.
    assert "release_reason='owner_changed'" in sql, sql
    assert "job_work_assignments.job_id = 5" in sql, sql
    assert "job_work_assignments.user_id = 8" in sql, sql
    # Tylko AKTYWNE przypisanie — propozycji automatu zmiana rekrutera nie rusza.
    assert "job_work_assignments.state = 'active'" in sql, sql

    # Drugi UPDATE dotyczy NOWEJ osoby: jej ręczne zdjęcie przestaje blokować.
    voided = _compiled(changed.execute.await_args_list[1].args[0])
    assert "release_reason='reassigned'" in voided, voided
    assert "job_work_assignments.user_id = 9" in voided, voided
    assert "job_work_assignments.release_reason = 'manual'" in voided, voided
    assert "job_work_assignments.state = 'released'" in voided, voided


@pytest.mark.asyncio
async def test_cleared_owner_only_releases_the_previous_person(monkeypatch):
    """PATCH z pustym `recruiter_id`: nie ma nowej osoby, więc nie ma czego
    odblokowywać ani przypisywać — zostaje zwolnienie poprzedniej."""
    from unittest.mock import AsyncMock

    from app.api import jobs as jobs_api

    manual_add = AsyncMock()
    monkeypatch.setattr(jobs_api, "manual_add", manual_add)
    db = AsyncMock()

    await jobs_api._sync_work_assignments_with_owner(
        db, job=_pool_job(), previous_owner_id=8, owner=None, actor_id=1
    )

    db.execute.assert_awaited_once()
    sql = _compiled(db.execute.await_args.args[0])
    assert "release_reason='owner_changed'" in sql, sql
    assert "job_work_assignments.user_id = 8" in sql, sql
    manual_add.assert_not_awaited()


# ── Claim (self-assign on unassigned) ────────────────────────────────────────


@pytest.mark.asyncio
async def test_claim_unassigned_as_recruiter_succeeds(ownership_client: AsyncClient):
    rec_id, rec_email, rec_pass = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job()  # no owner

    headers = await _login(ownership_client, rec_email, rec_pass)
    resp = await ownership_client.post(f"/api/jobs/{job_id}/claim", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["primary_owner"]["id"] == rec_id


@pytest.mark.asyncio
async def test_claim_already_owned_returns_409(ownership_client: AsyncClient):
    owner_id, _, _ = await _seed_user(UserRole.recruiter)
    _, challenger_email, challenger_pass = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(recruiter_id=owner_id)

    headers = await _login(ownership_client, challenger_email, challenger_pass)
    resp = await ownership_client.post(f"/api/jobs/{job_id}/claim", headers=headers)
    assert resp.status_code == 409, resp.text
    # Jedna nazwa roli na wszystkich ekranach: „Rekruter”, nie „właściciel”.
    assert resp.json()["detail"] == "Ta rekrutacja ma już rekrutera"


@pytest.mark.asyncio
async def test_claim_in_the_pool_registers_the_work_assignment(
    ownership_client: AsyncClient,
):
    """Przejęcie requestu z puli zakłada ręczne przypisanie — pulpit „Requesty
    i obłożenie” i automat widzą tę osobę od razu, nie po następnym przebiegu."""
    rec_id, rec_email, rec_pass = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(in_pool=True)
    try:
        headers = await _login(ownership_client, rec_email, rec_pass)
        resp = await ownership_client.post(f"/api/jobs/{job_id}/claim", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["primary_owner"]["id"] == rec_id
        assert [(p["user_id"], p["role"], p["via"]) for p in body["recruiters"]] == [
            (rec_id, "recruiter", "owner")
        ]
        # Rekruter przejmuje, ale obsady innych nie układa i priorytetu nie ustawia.
        assert body["can_staff"] is False
        assert body["can_set_priority"] is False
        assert await _work_rows(job_id) == [
            (rec_id, "active", "manual", "recruiter", None)
        ]
    finally:
        await _drop_jobs([job_id])


@pytest.mark.asyncio
async def test_claim_job_of_an_inactive_owner_succeeds(ownership_client: AsyncClient):
    """Runda 9 (R9-V2-2): prowadzący z nieaktywnym kontem to brak prowadzącego —
    rekrutację da się przejąć, a odpowiedź mówi, że konto jest nieaktywne."""
    owner_id, _, _ = await _seed_user(UserRole.recruiter)
    rec_id, rec_email, rec_pass = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(recruiter_id=owner_id)
    headers = await _login(ownership_client, rec_email, rec_pass)
    async with AsyncSessionLocal() as db:
        owner = await db.get(User, owner_id)
        owner.is_active = False
        await db.commit()

    detail = await ownership_client.get(f"/api/jobs/{job_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["primary_owner"]["is_active"] is False

    resp = await ownership_client.post(f"/api/jobs/{job_id}/claim", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["primary_owner"]["id"] == rec_id
    assert resp.json()["primary_owner"]["is_active"] is True


@pytest.mark.asyncio
async def test_claim_closed_job_returns_409(ownership_client: AsyncClient):
    """Runda 8 (R8-X2-3): zamkniętej rekrutacji bez prowadzącego (archiwum
    z Traffita) nikt nie przejmuje — „prowadzący” widział stawki umów B2B
    wydanych w tej rekrutacji."""
    _, rec_email, rec_pass = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(status=JobStatus.closed)

    headers = await _login(ownership_client, rec_email, rec_pass)
    resp = await ownership_client.post(f"/api/jobs/{job_id}/claim", headers=headers)
    assert resp.status_code == 409, resp.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job is not None and job.recruiter_id is None


@pytest.mark.asyncio
async def test_claim_as_read_only_user_forbidden(ownership_client: AsyncClient):
    _, viewer_email, viewer_pass = await _seed_user(UserRole.user)
    job_id = await _seed_job()

    headers = await _login(ownership_client, viewer_email, viewer_pass)
    resp = await ownership_client.post(f"/api/jobs/{job_id}/claim", headers=headers)
    assert resp.status_code == 403, resp.text


# ── Mine filter ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mine_filter_includes_primary_owner_jobs(
    ownership_client: AsyncClient,
):
    rec_id, rec_email, rec_pass = await _seed_user(UserRole.recruiter)
    job_id = await _seed_job(recruiter_id=rec_id)

    headers = await _login(ownership_client, rec_email, rec_pass)
    resp = await ownership_client.get("/api/jobs?mine=true", headers=headers)
    assert resp.status_code == 200, resp.text
    ids = [j["id"] for j in resp.json()["items"]]
    assert job_id in ids


@pytest.mark.asyncio
async def test_mine_filter_excludes_foreign_jobs(ownership_client: AsyncClient):
    stranger_id, _, _ = await _seed_user(UserRole.recruiter)
    _, viewer_email, viewer_pass = await _seed_user(UserRole.recruiter)
    stranger_job = await _seed_job(recruiter_id=stranger_id)

    headers = await _login(ownership_client, viewer_email, viewer_pass)
    resp = await ownership_client.get("/api/jobs?mine=true", headers=headers)
    assert resp.status_code == 200, resp.text
    ids = [j["id"] for j in resp.json()["items"]]
    assert stranger_job not in ids


@pytest.mark.asyncio
async def test_mine_filter_includes_collaborator_jobs(
    ownership_client: AsyncClient,
):
    owner_id, owner_email, owner_pass = await _seed_user(UserRole.recruiter)
    collab_id, collab_email, collab_pass = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)

    # Owner adds the sourcer as a collaborator (primary owner → allowed)
    owner_headers = await _login(ownership_client, owner_email, owner_pass)
    add = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=owner_headers,
        json={"user_id": collab_id},
    )
    assert add.status_code == 201, add.text

    # Now the sourcer's "mine" should include the job
    collab_headers = await _login(ownership_client, collab_email, collab_pass)
    resp = await ownership_client.get("/api/jobs?mine=true", headers=collab_headers)
    assert resp.status_code == 200
    ids = [j["id"] for j in resp.json()["items"]]
    assert job_id in ids


# ── Collaborator permissions ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_collaborator_add_by_primary_succeeds(ownership_client: AsyncClient):
    owner_id, owner_email, owner_pass = await _seed_user(UserRole.recruiter)
    collab_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)

    headers = await _login(ownership_client, owner_email, owner_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=headers,
        json={"user_id": collab_id},
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_collaborator_add_by_recruiter_outside_the_job_succeeds(
    ownership_client: AsyncClient,
):
    """Decyzja 29.09.2026: współpracowników dopisuje każdy, kto redaguje
    rekrutację (``ensure_job_editor``) — także rekruter spoza jej zespołu.
    Każde dodanie i usunięcie zostawia wpis w historii."""
    from app.models.activity import Activity

    owner_id, _, _ = await _seed_user(UserRole.recruiter)
    _, stranger_email, stranger_pass = await _seed_user(UserRole.recruiter)
    collab_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)

    headers = await _login(ownership_client, stranger_email, stranger_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=headers,
        json={"user_id": collab_id},
    )
    assert resp.status_code == 201, resp.text
    removed = await ownership_client.delete(
        f"/api/jobs/{job_id}/collaborators/{collab_id}", headers=headers
    )
    assert removed.status_code == 204, removed.text

    async with AsyncSessionLocal() as db:
        actions = set(
            (
                await db.execute(
                    select(Activity.action).where(
                        Activity.entity_type == "job", Activity.entity_id == job_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert {"collaborator_added", "collaborator_removed"} <= actions


@pytest.mark.asyncio
async def test_collaborator_add_and_remove_by_read_only_viewer_forbidden(
    ownership_client: AsyncClient,
):
    owner_id, _, _ = await _seed_user(UserRole.recruiter)
    _, viewer_email, viewer_pass = await _seed_user(UserRole.user)
    collab_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)
    async with AsyncSessionLocal() as db:
        from app.models.job_collaborator import JobCollaborator

        db.add(JobCollaborator(job_id=job_id, user_id=collab_id, added_by=owner_id))
        await db.commit()

    headers = await _login(ownership_client, viewer_email, viewer_pass)
    add = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=headers,
        json={"user_id": collab_id},
    )
    assert add.status_code == 403, add.text
    remove = await ownership_client.delete(
        f"/api/jobs/{job_id}/collaborators/{collab_id}", headers=headers
    )
    assert remove.status_code == 403, remove.text


@pytest.mark.asyncio
async def test_manual_add_promotes_an_auto_cc_collaborator(
    ownership_client: AsyncClient,
):
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource

    owner_id, owner_email, owner_pass = await _seed_user(UserRole.recruiter)
    collab_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)
    async with AsyncSessionLocal() as db:
        db.add(
            JobCollaborator(
                job_id=job_id,
                user_id=collab_id,
                source=JobCollaboratorSource.auto_cc,
            )
        )
        await db.commit()

    headers = await _login(ownership_client, owner_email, owner_pass)
    resp = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=headers,
        json={"user_id": collab_id},
    )
    assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobCollaborator).where(
                JobCollaborator.job_id == job_id,
                JobCollaborator.user_id == collab_id,
            )
        )
        assert row is not None
        assert row.source == JobCollaboratorSource.manual
        assert row.added_by == owner_id

    detail = await ownership_client.get(f"/api/jobs/{job_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert [(c["id"], c["source"]) for c in detail.json()["collaborators"]] == [
        (collab_id, "manual")
    ]


@pytest.mark.asyncio
async def test_removing_a_category_participant_keeps_a_flagged_row(
    ownership_client: AsyncClient,
):
    """Wiersz ``auto_cc`` nie znika — flaga blokuje powrót osoby z kategorii."""
    from app.models.activity import Activity
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource

    owner_id, owner_email, owner_pass = await _seed_user(UserRole.recruiter)
    collab_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)
    async with AsyncSessionLocal() as db:
        db.add(
            JobCollaborator(
                job_id=job_id,
                user_id=collab_id,
                source=JobCollaboratorSource.auto_cc,
            )
        )
        await db.commit()

    headers = await _login(ownership_client, owner_email, owner_pass)
    listed = await ownership_client.get(
        f"/api/jobs/{job_id}/collaborators", headers=headers
    )
    assert [row["id"] for row in listed.json()] == [collab_id]

    removed = await ownership_client.delete(
        f"/api/jobs/{job_id}/collaborators/{collab_id}", headers=headers
    )
    assert removed.status_code == 204, removed.text
    # Powtórzone zdjęcie jest sukcesem i nie zostawia drugiego wpisu w historii.
    again = await ownership_client.delete(
        f"/api/jobs/{job_id}/collaborators/{collab_id}", headers=headers
    )
    assert again.status_code == 204, again.text

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobCollaborator).where(
                JobCollaborator.job_id == job_id,
                JobCollaborator.user_id == collab_id,
            )
        )
        assert row is not None
        assert row.source == JobCollaboratorSource.auto_cc
        assert row.removed_from_auto_cc is True
        assert row.removed_at is not None
        actions = (
            await db.scalars(
                select(Activity.action).where(
                    Activity.entity_type == "job", Activity.entity_id == job_id
                )
            )
        ).all()
    assert list(actions).count("collaborator_removed_auto_cc") == 1

    listed = await ownership_client.get(
        f"/api/jobs/{job_id}/collaborators", headers=headers
    )
    assert listed.status_code == 200, listed.text
    assert listed.json() == []
    detail = await ownership_client.get(f"/api/jobs/{job_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["collaborators"] == []

    # Ręczne dopisanie tej samej osoby zdejmuje flagę — to świadomy wybór.
    back = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=headers,
        json={"user_id": collab_id},
    )
    assert back.status_code == 201, back.text
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobCollaborator).where(
                JobCollaborator.job_id == job_id,
                JobCollaborator.user_id == collab_id,
            )
        )
        assert row.source == JobCollaboratorSource.manual
        assert row.removed_from_auto_cc is False
        assert row.removed_at is None


@pytest.mark.asyncio
async def test_patch_category_swaps_category_participants(
    ownership_client: AsyncClient,
):
    """Zmiana kategorii w PATCH wymienia uczestników w tej samej transakcji."""
    from sqlalchemy import delete

    from app.models.competence_category import (
        CompetenceCategory,
        UserCompetenceCategory,
    )
    from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource

    _, admin_email, admin_pass = await _seed_user(UserRole.admin)
    old_member, _, _ = await _seed_user(UserRole.sourcer)
    new_first, _, _ = await _seed_user(UserRole.recruiter)
    new_second, _, _ = await _seed_user(UserRole.sourcer)
    removed_earlier, _, _ = await _seed_user(UserRole.sourcer)
    manual, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(status=JobStatus.published)
    async with AsyncSessionLocal() as db:
        categories = []
        for _ in range(2):
            tag = uuid.uuid4().hex[:8]
            category = CompetenceCategory(
                slug=f"own-{tag}",
                name_pl=f"Kategoria {tag}",
                name_en=f"Category {tag}",
                description="kategoria testowa uczestników",
                keywords=[],
                is_active=True,
                display_order=99,
            )
            db.add(category)
            categories.append(category)
        await db.flush()
        old_cc, new_cc = categories[0].id, categories[1].id
        for user_id, category_id, priority in (
            (old_member, old_cc, 1),
            (new_first, new_cc, 1),
            (new_second, new_cc, 2),
            (removed_earlier, new_cc, 2),
        ):
            db.add(
                UserCompetenceCategory(
                    user_id=user_id,
                    competence_category_id=category_id,
                    priority=priority,
                    is_primary=priority == 1,
                )
            )
        job = await db.get(Job, job_id)
        job.competence_category_id = old_cc
        db.add_all(
            [
                JobCollaborator(
                    job_id=job_id,
                    user_id=old_member,
                    source=JobCollaboratorSource.auto_cc,
                ),
                JobCollaborator(
                    job_id=job_id, user_id=manual, source=JobCollaboratorSource.manual
                ),
                JobCollaborator(
                    job_id=job_id,
                    user_id=removed_earlier,
                    source=JobCollaboratorSource.auto_cc,
                    removed_from_auto_cc=True,
                ),
            ]
        )
        await db.commit()

    try:
        headers = await _login(ownership_client, admin_email, admin_pass)
        resp = await ownership_client.patch(
            f"/api/jobs/{job_id}",
            headers=headers,
            json={"competence_category_id": new_cc},
        )
        assert resp.status_code == 200, resp.text

        async with AsyncSessionLocal() as db:
            rows = {
                user_id: (source.value, removed)
                for user_id, source, removed in (
                    await db.execute(
                        select(
                            JobCollaborator.user_id,
                            JobCollaborator.source,
                            JobCollaborator.removed_from_auto_cc,
                        ).where(JobCollaborator.job_id == job_id)
                    )
                ).all()
            }
        assert rows == {
            new_first: ("auto_cc", False),
            new_second: ("auto_cc", False),
            manual: ("manual", False),
            # Osoba zdjęta wcześniej z tej rekrutacji nie wraca z kategorią.
            removed_earlier: ("auto_cc", True),
        }
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Job).where(Job.id == job_id))
            await db.execute(
                delete(CompetenceCategory).where(
                    CompetenceCategory.id.in_([old_cc, new_cc])
                )
            )
            await db.commit()


@pytest.mark.asyncio
async def test_collaborator_add_duplicate_is_idempotent(
    ownership_client: AsyncClient,
):
    owner_id, owner_email, owner_pass = await _seed_user(UserRole.recruiter)
    collab_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)
    headers = await _login(ownership_client, owner_email, owner_pass)

    r1 = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=headers,
        json={"user_id": collab_id},
    )
    r2 = await ownership_client.post(
        f"/api/jobs/{job_id}/collaborators",
        headers=headers,
        json={"user_id": collab_id},
    )
    assert r1.status_code == 201
    assert r2.status_code == 201
    # One row, not two
    async with AsyncSessionLocal() as db:
        from app.models.job_collaborator import JobCollaborator

        rows = (
            (
                await db.execute(
                    select(JobCollaborator).where(
                        JobCollaborator.job_id == job_id,
                        JobCollaborator.user_id == collab_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_collaborator_remove_by_dl_succeeds(ownership_client: AsyncClient):
    dl_id, dl_email, dl_pass = await _seed_user(UserRole.delivery_lead)
    owner_id, _, _ = await _seed_user(UserRole.recruiter)
    collab_id, _, _ = await _seed_user(UserRole.sourcer)
    job_id = await _seed_job(recruiter_id=owner_id)
    await _grant_dl_job_scope(dl_id, job_id)

    async with AsyncSessionLocal() as db:
        from app.models.job_collaborator import JobCollaborator

        db.add(JobCollaborator(job_id=job_id, user_id=collab_id, added_by=owner_id))
        await db.commit()

    headers = await _login(ownership_client, dl_email, dl_pass)
    resp = await ownership_client.delete(
        f"/api/jobs/{job_id}/collaborators/{collab_id}", headers=headers
    )
    assert resp.status_code == 204, resp.text


# ── /api/users directory ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_users_directory_excludes_read_only_viewers(
    ownership_client: AsyncClient,
):
    _, rec_email, rec_pass = await _seed_user(UserRole.recruiter)
    viewer_id, _, _ = await _seed_user(UserRole.user)

    headers = await _login(ownership_client, rec_email, rec_pass)
    resp = await ownership_client.get("/api/users", headers=headers)
    assert resp.status_code == 200, resp.text
    ids = [u["id"] for u in resp.json()]
    assert viewer_id not in ids


@pytest.mark.asyncio
async def test_users_directory_respects_roles_filter(ownership_client: AsyncClient):
    rec_id, rec_email, rec_pass = await _seed_user(UserRole.recruiter)
    sourcer_id, _, _ = await _seed_user(UserRole.sourcer)

    headers = await _login(ownership_client, rec_email, rec_pass)
    resp = await ownership_client.get("/api/users?roles=recruiter", headers=headers)
    assert resp.status_code == 200
    ids = [u["id"] for u in resp.json()]
    assert rec_id in ids
    assert sourcer_id not in ids


@pytest.mark.asyncio
async def test_users_directory_and_mentions_include_secondary_roles(
    ownership_client: AsyncClient,
):
    _, requester_email, requester_password = await _seed_user(UserRole.recruiter)
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        hybrid = User(
            email=f"hybrid-recruiter-tac-{unique}@example.com",
            password_hash=hash_password(f"T3st_{unique}!HYBRID"),
            name=f"Hybrid TAC {unique}",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value, UserRole.tac.value],
            is_active=True,
        )
        db.add(hybrid)
        await db.commit()
        await db.refresh(hybrid)
        hybrid_id = hybrid.id

    headers = await _login(
        ownership_client,
        requester_email,
        requester_password,
    )
    directory = await ownership_client.get(
        "/api/users?roles=tac",
        headers=headers,
    )
    mentionable = await ownership_client.get(
        "/api/users/mentionable",
        headers=headers,
    )

    assert directory.status_code == 200, directory.text
    assert mentionable.status_code == 200, mentionable.text
    directory_row = next(user for user in directory.json() if user["id"] == hybrid_id)
    assert directory_row["role"] == UserRole.recruiter.value
    assert UserRole.tac.value in directory_row["roles"]
    assert hybrid_id in {user["id"] for user in mentionable.json()}
