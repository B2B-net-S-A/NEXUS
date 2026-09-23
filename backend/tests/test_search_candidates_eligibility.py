"""Ręczna wyszukiwarka niesie plakietkę dopuszczalności w kontekście rekrutacji.

``POST /api/search/candidates`` z ``exclude_in_job_id`` ocenia wiersze strony
tą samą polityką co ranking AI: konflikt z klientem (NDA) → ostrzeżenie
(``assignment_allowed=True``), weto hiring managera → ``assignment_allowed=False``.
Bez kontekstu rekrutacji ``eligibility`` jest ``None``.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import select

SEARCH = "/api/search/candidates"


def _token() -> str:
    # letters only → the word-prefix FTS route of the boolean search
    return "elig" + "".join(chr(ord("a") + int(c, 16) % 26) for c in uuid.uuid4().hex)


async def _seed_nda_world(token: str) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.candidate_conflict import CandidateConflict, ConflictType
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"SearchElig-{token}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"SearchElig {token}", status=JobStatus.published, client_id=client.id
        )
        nda = Candidate(
            name="Nda",
            lastname=token,
            email=f"{token}-nda@example.com",
            status=CandidateStatus.active,
        )
        clean = Candidate(
            name="Clean",
            lastname=token,
            email=f"{token}-clean@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, nda, clean])
        await db.flush()
        db.add(
            CandidateConflict(
                candidate_id=nda.id,
                client_id=client.id,
                type=ConflictType.nda,
                active=True,
            )
        )
        await db.commit()
        return {"job_id": job.id, "nda": nda.id, "clean": clean.id}


async def _search(app_client, headers, token, job_id=None) -> dict[int, dict]:
    body = {"q_all": [token], "page_size": 50}
    if job_id is not None:
        body["exclude_in_job_id"] = job_id
    resp = await app_client.post(SEARCH, headers=headers, json=body)
    assert resp.status_code == 200, resp.text
    return {item["id"]: item for item in resp.json()["items"]}


async def test_nda_candidate_carries_a_warning_badge_in_job_context(
    app_client: AsyncClient, app_auth_headers: dict
):
    token = _token()
    world = await _seed_nda_world(token)

    items = await _search(app_client, app_auth_headers, token, world["job_id"])

    assert {world["nda"], world["clean"]} <= set(items)
    badge = items[world["nda"]]["eligibility"]
    assert badge["reason_code"] == "client_nda"
    assert badge["assignment_allowed"] is True
    assert badge["severity"] == "warning"
    assert items[world["clean"]]["eligibility"] is None


async def test_no_job_context_means_no_badge(
    app_client: AsyncClient, app_auth_headers: dict
):
    token = _token()
    world = await _seed_nda_world(token)

    items = await _search(app_client, app_auth_headers, token)

    assert world["nda"] in items
    assert items[world["nda"]]["eligibility"] is None


async def test_hiring_manager_veto_is_not_assignable(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from tests.test_manager_rejection_gate import _seed_vetoed_candidate

    world = await _seed_vetoed_candidate()
    token = _token()
    async with AsyncSessionLocal() as db:
        cand = await db.scalar(
            select(Candidate).where(Candidate.id == world["candidate_id"])
        )
        cand.lastname = token
        await db.commit()

    items = await _search(app_client, app_auth_headers, token, world["target_job_id"])

    badge = items[world["candidate_id"]]["eligibility"]
    assert badge["reason_code"] == "rejected_by_hiring_manager"
    assert badge["assignment_allowed"] is False


async def test_recruiter_outside_the_team_sees_the_badges(app_client: AsyncClient):
    # Plakietka niesie werdykt hiring managera tej rekrutacji, więc wymaga
    # odczytu rekrutacji. Od 23.09.2026 ma go każda rola wewnętrzna — także
    # rekruter spoza zespołu („nie musisz być przypisany").
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    token = _token()
    world = await _seed_nda_world(token)
    suffix = uuid.uuid4().hex[:8]
    email = f"search-elig-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Rekruter spoza zespołu",
                role=UserRole.recruiter,
                roles=[UserRole.recruiter.value],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    items = await _search(app_client, headers, token, world["job_id"])
    assert world["nda"] in items
    badge = items[world["nda"]]["eligibility"]
    assert badge is not None
    assert badge["reason_code"] == "client_nda"
    assert badge["assignment_allowed"] is True
    assert items[world["clean"]]["eligibility"] is None
