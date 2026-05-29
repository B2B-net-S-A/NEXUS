"""Multi-value filter tests for /api/jobs.

Verifies that `status`, `owner_id`, `client_id`, `competence_category_id` and
`responsible_id` accept repeated query params (single-value calls stay
backward-compatible), and that the `needs_sourcing`, `active_in_search` and
`deadline_*` filters narrow the result set correctly.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient


async def _seed_user(*, role: str = "recruiter") -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"job-flt-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("test-pass"),
            name=f"JobFlt-{uuid.uuid4().hex[:6]}",
            role=UserRole(role),
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_client() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        c = Client(name=f"JobFltClient-{uuid.uuid4().hex[:6]}")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_cc() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.competence_category import CompetenceCategory

    async with AsyncSessionLocal() as db:
        cc = CompetenceCategory(
            slug=f"flt-{uuid.uuid4().hex[:8]}",
            name_pl=f"Kat-{uuid.uuid4().hex[:6]}",
            name_en=f"Cat-{uuid.uuid4().hex[:6]}",
            description="filter test category",
            keywords=[],
            is_active=True,
            display_order=99,
        )
        db.add(cc)
        await db.commit()
        await db.refresh(cc)
        return cc.id


async def _seed_job(
    *,
    status: str = "published",
    recruiter_id: int | None = None,
    delivery_lead_id: int | None = None,
    tac_id: int | None = None,
    competence_category_id: int | None = None,
    needs_sourcing: bool = False,
    deadline: date | None = None,
    client_id: int | None = None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    if client_id is None:
        client_id = await _seed_client()
    async with AsyncSessionLocal() as db:
        j = Job(
            title=f"Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus(status),
            recruiter_id=recruiter_id,
            delivery_lead_id=delivery_lead_id,
            tac_id=tac_id,
            competence_category_id=competence_category_id,
            needs_sourcing=needs_sourcing,
            deadline=deadline,
            client_id=client_id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _add_collaborator(
    job_id: int, user_id: int, *, removed: bool = False
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job_collaborator import JobCollaborator

    async with AsyncSessionLocal() as db:
        db.add(
            JobCollaborator(
                job_id=job_id,
                user_id=user_id,
                added_by=user_id,
                removed_from_auto_cc=removed,
            )
        )
        await db.commit()


async def _cleanup(
    *,
    job_ids: list[int],
    user_ids: list[int],
    cc_ids: list[int] | None = None,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.competence_category import CompetenceCategory
    from app.models.job import Job
    from app.models.user import User
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        # Jobs first — FK references to users/CC, and job_collaborators cascade.
        for jid in job_ids:
            await db.execute(delete(Job).where(Job.id == jid))
        for uid in user_ids:
            await db.execute(delete(User).where(User.id == uid))
        for ccid in cc_ids or []:
            await db.execute(
                delete(CompetenceCategory).where(CompetenceCategory.id == ccid)
            )
        await db.commit()


@pytest.mark.asyncio
async def test_jobs_status_filter_accepts_multiple_values(
    app_client: AsyncClient, app_auth_headers: dict
):
    pub = await _seed_job(status="published")
    drf = await _seed_job(status="draft")
    cls = await _seed_job(status="closed")
    try:
        r = await app_client.get(
            "/api/jobs?status=published&status=draft&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert pub in ids
        assert drf in ids
        assert cls not in ids
    finally:
        await _cleanup(job_ids=[pub, drf, cls], user_ids=[])


@pytest.mark.asyncio
async def test_jobs_status_single_value_back_compat(
    app_client: AsyncClient, app_auth_headers: dict
):
    pub = await _seed_job(status="published")
    drf = await _seed_job(status="draft")
    try:
        r = await app_client.get(
            "/api/jobs?status=published&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert pub in ids
        assert drf not in ids
    finally:
        await _cleanup(job_ids=[pub, drf], user_ids=[])


@pytest.mark.asyncio
async def test_jobs_owner_id_filter_accepts_multiple(
    app_client: AsyncClient, app_auth_headers: dict
):
    u1 = await _seed_user()
    u2 = await _seed_user()
    j1 = await _seed_job(status="published", recruiter_id=u1)
    j2 = await _seed_job(status="published", recruiter_id=u2)
    j_orphan = await _seed_job(status="published", recruiter_id=None)
    try:
        r = await app_client.get(
            f"/api/jobs?owner_id={u1}&owner_id={u2}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert j1 in ids
        assert j2 in ids
        assert j_orphan not in ids
    finally:
        await _cleanup(job_ids=[j1, j2, j_orphan], user_ids=[u1, u2])


@pytest.mark.asyncio
async def test_jobs_client_id_filter_accepts_multiple(
    app_client: AsyncClient, app_auth_headers: dict
):
    c1 = await _seed_client()
    c2 = await _seed_client()
    j1 = await _seed_job(client_id=c1)
    j2 = await _seed_job(client_id=c2)
    j_other = await _seed_job()
    try:
        r = await app_client.get(
            f"/api/jobs?client_id={c1}&client_id={c2}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert j1 in ids
        assert j2 in ids
        assert j_other not in ids
    finally:
        await _cleanup(job_ids=[j1, j2, j_other], user_ids=[])


@pytest.mark.asyncio
async def test_jobs_client_id_single_value_back_compat(
    app_client: AsyncClient, app_auth_headers: dict
):
    c1 = await _seed_client()
    j1 = await _seed_job(client_id=c1)
    j_other = await _seed_job()
    try:
        r = await app_client.get(
            f"/api/jobs?client_id={c1}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert j1 in ids
        assert j_other not in ids
    finally:
        await _cleanup(job_ids=[j1, j_other], user_ids=[])


@pytest.mark.asyncio
async def test_jobs_competence_category_filter(
    app_client: AsyncClient, app_auth_headers: dict
):
    cc1 = await _seed_cc()
    cc2 = await _seed_cc()
    j1 = await _seed_job(competence_category_id=cc1)
    j2 = await _seed_job(competence_category_id=cc2)
    j_none = await _seed_job()
    try:
        r = await app_client.get(
            f"/api/jobs?competence_category_id={cc1}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert j1 in ids
        assert j2 not in ids
        assert j_none not in ids
    finally:
        await _cleanup(job_ids=[j1, j2, j_none], user_ids=[], cc_ids=[cc1, cc2])


@pytest.mark.asyncio
async def test_jobs_responsible_id_matches_recruiter_dl_tac(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`responsible_id` matches the recruiter, delivery lead, OR tac role —
    unlike `owner_id`, which only matches recruiter_id."""
    u_rec = await _seed_user()
    u_dl = await _seed_user(role="delivery_lead")
    u_tac = await _seed_user(role="tac")
    j_rec = await _seed_job(recruiter_id=u_rec)
    j_dl = await _seed_job(delivery_lead_id=u_dl)
    j_tac = await _seed_job(tac_id=u_tac)
    j_none = await _seed_job()
    try:
        # All three roles in one query.
        r = await app_client.get(
            f"/api/jobs?responsible_id={u_rec}&responsible_id={u_dl}"
            f"&responsible_id={u_tac}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert {j_rec, j_dl, j_tac} <= ids
        assert j_none not in ids

        # A DL-only id matches the job where the user is the delivery lead.
        r2 = await app_client.get(
            f"/api/jobs?responsible_id={u_dl}&page_size=100",
            headers=app_auth_headers,
        )
        ids2 = {item["id"] for item in r2.json()["items"]}
        assert j_dl in ids2
        assert j_rec not in ids2
        assert j_tac not in ids2
    finally:
        await _cleanup(
            job_ids=[j_rec, j_dl, j_tac, j_none],
            user_ids=[u_rec, u_dl, u_tac],
        )


@pytest.mark.asyncio
async def test_jobs_needs_sourcing_filter(
    app_client: AsyncClient, app_auth_headers: dict
):
    j_src = await _seed_job(needs_sourcing=True)
    j_no = await _seed_job(needs_sourcing=False)
    try:
        r = await app_client.get(
            "/api/jobs?needs_sourcing=true&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert j_src in ids
        assert j_no not in ids
    finally:
        await _cleanup(job_ids=[j_src, j_no], user_ids=[])


@pytest.mark.asyncio
async def test_jobs_active_in_search_filter(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A job is 'active in search' when it has ≥1 collaborator with
    removed_from_auto_cc=False. A soft-removed collaborator does not count."""
    u = await _seed_user()
    j_active = await _seed_job()
    j_removed = await _seed_job()
    j_none = await _seed_job()
    await _add_collaborator(j_active, u, removed=False)
    await _add_collaborator(j_removed, u, removed=True)
    try:
        r = await app_client.get(
            "/api/jobs?active_in_search=true&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert j_active in ids
        assert j_removed not in ids
        assert j_none not in ids

        r2 = await app_client.get(
            "/api/jobs?active_in_search=false&page_size=100",
            headers=app_auth_headers,
        )
        ids2 = {item["id"] for item in r2.json()["items"]}
        assert j_active not in ids2
        # No active collaborator → counts as "not active in search".
        assert j_removed in ids2
        assert j_none in ids2
    finally:
        await _cleanup(job_ids=[j_active, j_removed, j_none], user_ids=[u])


@pytest.mark.asyncio
async def test_jobs_deadline_range_and_has_deadline(
    app_client: AsyncClient, app_auth_headers: dict
):
    today = date.today()
    j_past = await _seed_job(deadline=today - timedelta(days=10))
    j_soon = await _seed_job(deadline=today + timedelta(days=3))
    j_far = await _seed_job(deadline=today + timedelta(days=60))
    j_none = await _seed_job(deadline=None)
    mine = [j_past, j_soon, j_far, j_none]
    try:
        # Overdue: deadline strictly before today (upper bound = yesterday).
        yesterday = (today - timedelta(days=1)).isoformat()
        r = await app_client.get(
            f"/api/jobs?deadline_to={yesterday}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert j_past in ids
        assert j_soon not in ids
        assert j_far not in ids
        assert j_none not in ids

        # Window [today, today+7] → only j_soon.
        r2 = await app_client.get(
            f"/api/jobs?deadline_from={today.isoformat()}"
            f"&deadline_to={(today + timedelta(days=7)).isoformat()}&page_size=100",
            headers=app_auth_headers,
        )
        ids2 = {item["id"] for item in r2.json()["items"]}
        assert j_soon in ids2
        assert j_past not in ids2
        assert j_far not in ids2
        assert j_none not in ids2

        # has_deadline=false → only the no-deadline job (among ours).
        r3 = await app_client.get(
            "/api/jobs?has_deadline=false&page_size=100",
            headers=app_auth_headers,
        )
        ids3 = {item["id"] for item in r3.json()["items"]}
        assert j_none in ids3
        assert j_past not in ids3
        assert j_soon not in ids3
        assert j_far not in ids3

        # has_deadline=true → the three dated jobs, not the null one.
        r4 = await app_client.get(
            "/api/jobs?has_deadline=true&page_size=100",
            headers=app_auth_headers,
        )
        ids4 = {item["id"] for item in r4.json()["items"]}
        assert {j_past, j_soon, j_far} <= ids4
        assert j_none not in ids4
    finally:
        await _cleanup(job_ids=mine, user_ids=[])
