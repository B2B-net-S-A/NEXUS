"""HTTP contract of the on-demand scoring surfaces: who may ask, and how often.

* The score column (`POST /api/search/candidates/scores`) shows the canonical
  fit C2 shows. A recruiter, sourcer or TAC outside the job team already sees
  that number on `/candidate-search/runs`, `/pipeline-scores`, `/ai-matches`
  and the job page, so the column uses the same guard (pipeline section read +
  the recruitment exists) — not the team-membership guard it had until 11.09.
* Both the column and the "Dopasowanie" thumbs (`…/scoring/{job}/feedback`)
  measure on demand, so both carry a rate limit.

Real Postgres and real auth. Vector providers are stubbed (no network).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient

import app.models  # noqa: F401  (register every mapper)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.section_permission import UserSectionOverride
from app.models.user import User, UserRole
from app.services import canonical_fit

SCORES = "/api/search/candidates/scores"


async def _user(role: UserRole, *, pipeline: str | None = None) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"scores-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Scores"),
            name=f"Scores {role.value}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        if pipeline is not None:
            db.add(UserSectionOverride(user_id=user.id, section="pipeline", access=pipeline))
        await db.commit()
        user_id = user.id
    return {"Authorization": f"Bearer {create_access_token(user_id, role.value)}"}


async def _recruitment() -> dict:
    """A job nobody is on the team of, and one candidate."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Scores matrix {tag}")
        db.add(client)
        await db.flush()
        job = Job(title=f"Go developer {tag}", client_id=client.id, must_skills=["Go"])
        candidate = Candidate(name="Kolumna", lastname=f"Wyników {tag}", skills=["Go"])
        db.add_all([job, candidate])
        await db.commit()
        return {"job_id": job.id, "candidate_id": candidate.id}


@pytest.fixture
def no_vectors(monkeypatch):
    monkeypatch.setattr(canonical_fit, "request_vector", AsyncMock(return_value=None))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role,pipeline,expected",
    [
        # Outside the job team: the same number is on their C2 screens.
        (UserRole.recruiter, None, 200),
        (UserRole.sourcer, None, 200),
        (UserRole.tac, None, 200),
        # Still candidate search, but no recruitment (pipeline) section.
        (UserRole.recruiter, "none", 403),
        # The read-only viewer persona never reaches candidate search.
        (UserRole.user, None, 403),
    ],
)
async def test_score_column_access_follows_the_full_search_guard(
    app_client: AsyncClient, no_vectors, role, pipeline, expected
):
    world = await _recruitment()
    headers = await _user(role, pipeline=pipeline)

    response = await app_client.post(
        SCORES,
        json={"job_id": world["job_id"], "candidate_ids": [world["candidate_id"]]},
        headers=headers,
    )

    assert response.status_code == expected, response.text
    if expected == 200:
        body = response.json()
        # No vector in tests: "not measured" with its reason, never a 0.
        assert body["scores"] == {}
        assert body["breakdowns"][str(world["candidate_id"])] == {
            "total": None,
            "measurement": "unavailable",
        }
        assert body["profile_key"]


@pytest.mark.asyncio
async def test_score_column_missing_recruitment_and_oversized_request(
    app_client: AsyncClient, no_vectors
):
    headers = await _user(UserRole.recruiter)

    missing = await app_client.post(
        SCORES, json={"job_id": 2_000_000_000, "candidate_ids": [1]}, headers=headers
    )
    oversized = await app_client.post(
        SCORES, json={"job_id": 1, "candidate_ids": list(range(1, 22))}, headers=headers
    )

    assert missing.status_code == 404, missing.text
    assert oversized.status_code == 422, oversized.text


async def _statuses(app_client: AsyncClient, call, count: int) -> list[int]:
    """`app_client` switches slowapi off for the session; switch it on here,
    in a bucket of this test's own (unique client address)."""
    from app.core.rate_limit import limiter

    limiter.enabled = True
    try:
        return [(await call()).status_code for _ in range(count)]
    finally:
        limiter.enabled = False
        limiter.reset()


def _own_bucket(headers: dict[str, str]) -> dict[str, str]:
    octet = uuid.uuid4().int % 250 + 1
    return {**headers, "X-Forwarded-For": f"198.51.100.{octet}"}


@pytest.mark.asyncio
async def test_score_column_is_rate_limited(app_client: AsyncClient):
    headers = _own_bucket(await _user(UserRole.recruiter))

    statuses = await _statuses(
        app_client,
        # Empty ids answer without measuring — the limit is what is under test.
        lambda: app_client.post(
            SCORES, json={"job_id": 1, "candidate_ids": []}, headers=headers
        ),
        61,
    )

    assert statuses[:60] == [200] * 60
    assert statuses[60] == 429


@pytest.mark.asyncio
async def test_scoring_feedback_is_rate_limited(app_client: AsyncClient):
    headers = _own_bucket(await _user(UserRole.recruiter))
    path = "/api/candidates/2000000000/scoring/2000000000/feedback"

    statuses = await _statuses(
        app_client,
        lambda: app_client.post(path, json={"rating": 1}, headers=headers),
        61,
    )

    # 404 = no justification to rate (checked before any measurement).
    assert statuses[:60] == [404] * 60
    assert statuses[60] == 429


def test_limited_routes_live_in_modules_without_future_annotations():
    """slowapi #579: with PEP 563 the body and the `Annotated` guards of a
    limited route turn into QUERY parameters — 422 on a valid request."""
    import ast
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / "app"
    for module, handler in (
        ("api/search.py", "candidate_match_scores"),
        ("api/candidate_scoring.py", "rate_scoring_justification"),
    ):
        tree = ast.parse((app_dir / module).read_text(encoding="utf-8"))
        assert not [
            alias
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "__future__"
            for alias in node.names
            if alias.name == "annotations"
        ], module
        (route,) = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == handler
        ]
        limits = [
            dec
            for dec in route.decorator_list
            if isinstance(dec, ast.Call)
            and isinstance(dec.func, ast.Attribute)
            and dec.func.attr == "limit"
        ]
        assert [ast.literal_eval(dec.args[0]) for dec in limits] == ["60/minute"]
