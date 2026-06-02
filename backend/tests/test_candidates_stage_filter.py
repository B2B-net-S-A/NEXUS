"""Tests for `GET /api/candidates?pipeline_stage=…&stage_category=…&stage_current_only=…`.

Filter semantics:

* `pipeline_stage` — multi-select OR over PipelineStage enum values.
* `stage_category` — coarse-grained OR over internal/external/terminal,
  expanded to the same enum value space and combined with `pipeline_stage`
  via OR.
* `stage_current_only` (default True) — match the LATEST stage per
  `(candidate_id, job_id)` pair. When False, match any historical move.

Uses the in-process `app_client` / `app_auth_headers` fixtures from conftest.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient


async def _seed_candidate(*, name_suffix: str = "") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Stage",
            lastname=f"Test-{uuid.uuid4().hex[:6]}{name_suffix}",
            email=f"stage-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"StageClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"Stage-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _seed_user() -> int:
    """Insert an active recruiter and return its id (for `moved_by` tests)."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        unique = uuid.uuid4().hex[:8]
        u = User(
            email=f"mover-{unique}@example.com",
            password_hash=hash_password(f"T3st_{unique}!PassX"),
            name=f"Mover {unique}",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_stage(
    candidate_id: int,
    job_id: int,
    stage_value: str,
    *,
    moved_at: datetime | None = None,
    moved_by: int | None = None,
) -> int:
    """Insert a CandidateStage row at the given pipeline stage.

    `moved_at` controls ordering — pass increasing timestamps when seeding
    multiple moves for the same `(candidate_id, job_id)` pair so the
    DISTINCT-ON-based "current stage" lookup is deterministic.
    `moved_by` is the user who performed the move (NULL = system/import).
    """
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        stage = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage(stage_value),
            moved_at=moved_at or datetime.now(timezone.utc),
            moved_by=moved_by,
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)
        return stage.id


async def _cleanup(
    *,
    candidate_ids: list[int] | None = None,
    job_ids: list[int] | None = None,
    user_ids: list[int] | None = None,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage
    from app.models.user import User
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for cid in candidate_ids or []:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.candidate_id == cid)
            )
            await db.execute(delete(Candidate).where(Candidate.id == cid))
        for jid in job_ids or []:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.job_id == jid)
            )
            await db.execute(delete(Job).where(Job.id == jid))
        for uid in user_ids or []:
            await db.execute(delete(User).where(User.id == uid))
        await db.commit()


@pytest.mark.asyncio
async def test_filter_pipeline_stage_single_value(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A candidate currently at `screening` shows up; one at `new` doesn't."""
    job_id = await _seed_job()
    target = await _seed_candidate(name_suffix="-A")
    other = await _seed_candidate(name_suffix="-B")
    await _seed_stage(target, job_id, "screening")
    await _seed_stage(other, job_id, "new")
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=screening&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert target in ids
        assert other not in ids
    finally:
        await _cleanup(candidate_ids=[target, other], job_ids=[job_id])


@pytest.mark.asyncio
async def test_filter_pipeline_stage_multi_value_or(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Multiple `pipeline_stage` params OR-combine — both candidates match."""
    job_id = await _seed_job()
    at_screening = await _seed_candidate(name_suffix="-S")
    at_interview = await _seed_candidate(name_suffix="-I")
    at_new = await _seed_candidate(name_suffix="-N")
    await _seed_stage(at_screening, job_id, "screening")
    await _seed_stage(at_interview, job_id, "interview")
    await _seed_stage(at_new, job_id, "new")
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=screening"
            "&pipeline_stage=interview&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert at_screening in ids
        assert at_interview in ids
        assert at_new not in ids
    finally:
        await _cleanup(
            candidate_ids=[at_screening, at_interview, at_new], job_ids=[job_id]
        )


@pytest.mark.asyncio
async def test_filter_stage_current_only_true_default(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`stage_current_only=true` (default) ignores historical `screening` row
    when the latest move is `rejected` — candidate must NOT appear when
    filtering for `screening`."""
    job_id = await _seed_job()
    cand = await _seed_candidate()
    base = datetime.now(timezone.utc) - timedelta(days=10)
    await _seed_stage(cand, job_id, "screening", moved_at=base)
    await _seed_stage(
        cand, job_id, "rejected", moved_at=base + timedelta(days=1)
    )
    try:
        # Default behaviour — latest move is `rejected`, so `screening` query
        # must NOT include this candidate.
        r = await app_client.get(
            "/api/candidates?pipeline_stage=screening&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert cand not in ids

        # But the same candidate IS at `rejected`, so the rejected query hits.
        r2 = await app_client.get(
            "/api/candidates?pipeline_stage=rejected&page_size=200",
            headers=app_auth_headers,
        )
        ids2 = [item["id"] for item in r2.json()["items"]]
        assert cand in ids2
    finally:
        await _cleanup(candidate_ids=[cand], job_ids=[job_id])


@pytest.mark.asyncio
async def test_filter_stage_current_only_false_matches_history(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`stage_current_only=false` matches any historical move — candidate
    that was once at `screening` (even though now `rejected`) IS returned."""
    job_id = await _seed_job()
    cand = await _seed_candidate()
    base = datetime.now(timezone.utc) - timedelta(days=10)
    await _seed_stage(cand, job_id, "screening", moved_at=base)
    await _seed_stage(
        cand, job_id, "rejected", moved_at=base + timedelta(days=1)
    )
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=screening"
            "&stage_current_only=false&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert cand in ids
    finally:
        await _cleanup(candidate_ids=[cand], job_ids=[job_id])


@pytest.mark.asyncio
async def test_filter_stage_category_external_expands_to_stages(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`stage_category=external` matches client_interview/acceptance/
    negotiation/onboarding — candidate at `client_interview` is returned,
    one at `screening` (internal) is not."""
    job_id = await _seed_job()
    at_client_interview = await _seed_candidate(name_suffix="-X")
    at_screening = await _seed_candidate(name_suffix="-S")
    await _seed_stage(at_client_interview, job_id, "client_interview")
    await _seed_stage(at_screening, job_id, "screening")
    try:
        r = await app_client.get(
            "/api/candidates?stage_category=external&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert at_client_interview in ids
        assert at_screening not in ids
    finally:
        await _cleanup(
            candidate_ids=[at_client_interview, at_screening], job_ids=[job_id]
        )


@pytest.mark.asyncio
async def test_filter_invalid_stage_returns_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    """FastAPI enum validation rejects non-enum stage values with 422."""
    r = await app_client.get(
        "/api/candidates?pipeline_stage=bogus_stage&page_size=10",
        headers=app_auth_headers,
    )
    assert r.status_code == 422


# ── "kto dodał na etap i kiedy" — stage_moved_by / stage_moved_after/before ──


@pytest.mark.asyncio
async def test_filter_stage_moved_by(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`stage_moved_by=<user>` returns only candidates whose matched stage move
    was performed by that user."""
    job_id = await _seed_job()
    mover_a = await _seed_user()
    mover_b = await _seed_user()
    by_a = await _seed_candidate(name_suffix="-A")
    by_b = await _seed_candidate(name_suffix="-B")
    await _seed_stage(by_a, job_id, "verified", moved_by=mover_a)
    await _seed_stage(by_b, job_id, "verified", moved_by=mover_b)
    try:
        r = await app_client.get(
            f"/api/candidates?stage_moved_by={mover_a}&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert by_a in ids
        assert by_b not in ids
    finally:
        await _cleanup(
            candidate_ids=[by_a, by_b],
            job_ids=[job_id],
            user_ids=[mover_a, mover_b],
        )


@pytest.mark.asyncio
async def test_filter_stage_moved_by_correlated_with_stage(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`pipeline_stage` + `stage_moved_by` are correlated on the SAME move.

    A candidate that user A moved to `verified` matches `verified`+A. A
    candidate that user A moved to `screening` (different stage) does NOT match
    `verified`+A — the who/when must apply to the matched stage move, not to
    any move by that user.
    """
    job_id = await _seed_job()
    mover_a = await _seed_user()
    verified_by_a = await _seed_candidate(name_suffix="-V")
    screening_by_a = await _seed_candidate(name_suffix="-S")
    await _seed_stage(verified_by_a, job_id, "verified", moved_by=mover_a)
    await _seed_stage(screening_by_a, job_id, "screening", moved_by=mover_a)
    try:
        r = await app_client.get(
            f"/api/candidates?pipeline_stage=verified&stage_moved_by={mover_a}"
            "&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert verified_by_a in ids
        assert screening_by_a not in ids
    finally:
        await _cleanup(
            candidate_ids=[verified_by_a, screening_by_a],
            job_ids=[job_id],
            user_ids=[mover_a],
        )


@pytest.mark.asyncio
async def test_filter_stage_moved_date_range(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`stage_moved_after`/`stage_moved_before` bound the move date inclusively."""
    job_id = await _seed_job()
    in_range = await _seed_candidate(name_suffix="-IN")
    too_old = await _seed_candidate(name_suffix="-OLD")
    # Fixed, timezone-aware instants well clear of UTC day boundaries.
    await _seed_stage(
        in_range,
        job_id,
        "verified",
        moved_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
    )
    await _seed_stage(
        too_old,
        job_id,
        "verified",
        moved_at=datetime(2026, 4, 1, 12, 0, tzinfo=timezone.utc),
    )
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=verified"
            "&stage_moved_after=2026-05-01&stage_moved_before=2026-05-31"
            "&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert in_range in ids
        assert too_old not in ids
    finally:
        await _cleanup(
            candidate_ids=[in_range, too_old], job_ids=[job_id]
        )


@pytest.mark.asyncio
async def test_filter_stage_moved_before_is_inclusive_of_whole_day(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A move late on the `stage_moved_before` day is still included (the bound
    is the start of the NEXT day, exclusive)."""
    job_id = await _seed_job()
    cand = await _seed_candidate()
    await _seed_stage(
        cand,
        job_id,
        "verified",
        moved_at=datetime(2026, 5, 31, 23, 30, tzinfo=timezone.utc),
    )
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=verified"
            "&stage_moved_before=2026-05-31&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert cand in ids
    finally:
        await _cleanup(candidate_ids=[cand], job_ids=[job_id])


@pytest.mark.asyncio
async def test_filter_stage_moved_by_without_stage_matches_any_move(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`stage_moved_by` with NO stage selected matches any candidate that user
    moved to any stage."""
    job_id = await _seed_job()
    mover_a = await _seed_user()
    moved = await _seed_candidate(name_suffix="-M")
    untouched = await _seed_candidate(name_suffix="-U")
    await _seed_stage(moved, job_id, "screening", moved_by=mover_a)
    await _seed_stage(untouched, job_id, "screening", moved_by=None)
    try:
        r = await app_client.get(
            f"/api/candidates?stage_moved_by={mover_a}&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert moved in ids
        assert untouched not in ids
    finally:
        await _cleanup(
            candidate_ids=[moved, untouched],
            job_ids=[job_id],
            user_ids=[mover_a],
        )


# ── Move-filter implies HISTORICAL matching (regression for the "kogo ──────────
# zweryfikowałem w maju" use case — candidates that progressed past the stage
# must still be returned). See `effective_current_only` in candidates.py. ──────


@pytest.mark.asyncio
async def test_stage_moved_by_matches_after_candidate_progressed(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A candidate that user A moved onto `verified` and who has SINCE moved on
    to `interview` must STILL match `pipeline_stage=verified&stage_moved_by=A`.

    This is the core regression: the recruiter asks "who did I verify" and must
    see everyone they verified, not just those still parked at `verified`. With
    the old `stage_current_only=true` default the candidate (current stage =
    `interview`) was silently dropped.
    """
    job_id = await _seed_job()
    mover_a = await _seed_user()
    progressed = await _seed_candidate(name_suffix="-PROG")
    base = datetime.now(timezone.utc) - timedelta(days=10)
    # A verifies the candidate, then the candidate advances to interview.
    await _seed_stage(progressed, job_id, "verified", moved_at=base, moved_by=mover_a)
    await _seed_stage(
        progressed,
        job_id,
        "interview",
        moved_at=base + timedelta(days=2),
        moved_by=mover_a,
    )
    try:
        r = await app_client.get(
            f"/api/candidates?pipeline_stage=verified&stage_moved_by={mover_a}"
            "&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert progressed in ids
    finally:
        await _cleanup(
            candidate_ids=[progressed], job_ids=[job_id], user_ids=[mover_a]
        )


@pytest.mark.asyncio
async def test_stage_moved_date_matches_after_candidate_progressed(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Same regression via the date-range filter: a candidate verified inside
    the window who then progressed past `verified` must still match."""
    job_id = await _seed_job()
    progressed = await _seed_candidate(name_suffix="-PROGD")
    await _seed_stage(
        progressed,
        job_id,
        "verified",
        moved_at=datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc),
    )
    await _seed_stage(
        progressed,
        job_id,
        "cv_sent",
        moved_at=datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc),
    )
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=verified"
            "&stage_moved_after=2026-05-01&stage_moved_before=2026-05-31"
            "&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert progressed in ids
    finally:
        await _cleanup(candidate_ids=[progressed], job_ids=[job_id])


@pytest.mark.asyncio
async def test_bare_stage_filter_stays_current_only_after_progression(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Guard: with NO move-filter, `pipeline_stage=verified` keeps current-only
    semantics — a candidate now at `interview` must NOT appear. (Ensures the
    auto-historical switch is scoped to move-filters only.)"""
    job_id = await _seed_job()
    progressed = await _seed_candidate(name_suffix="-BARE")
    base = datetime.now(timezone.utc) - timedelta(days=10)
    await _seed_stage(progressed, job_id, "verified", moved_at=base)
    await _seed_stage(
        progressed, job_id, "interview", moved_at=base + timedelta(days=2)
    )
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=verified&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert progressed not in ids
    finally:
        await _cleanup(candidate_ids=[progressed], job_ids=[job_id])


@pytest.mark.asyncio
async def test_stage_current_only_true_overrides_move_filter(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Explicit `stage_current_only=true` still restricts a move-filtered query
    to the candidate's CURRENT move — a candidate verified by A who progressed
    to `interview` must NOT match `verified&stage_moved_by=A&stage_current_only=true`."""
    job_id = await _seed_job()
    mover_a = await _seed_user()
    progressed = await _seed_candidate(name_suffix="-OVR")
    base = datetime.now(timezone.utc) - timedelta(days=10)
    await _seed_stage(progressed, job_id, "verified", moved_at=base, moved_by=mover_a)
    await _seed_stage(
        progressed,
        job_id,
        "interview",
        moved_at=base + timedelta(days=2),
        moved_by=mover_a,
    )
    try:
        r = await app_client.get(
            f"/api/candidates?pipeline_stage=verified&stage_moved_by={mover_a}"
            "&stage_current_only=true&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert progressed not in ids
    finally:
        await _cleanup(
            candidate_ids=[progressed], job_ids=[job_id], user_ids=[mover_a]
        )


# ── active_recruitments enrichment: KTO i KIEDY przeniósł kandydata na ─────────
# bieżący etap (popover „Rekrutacje" w liście). Sama atrybucja pochodzi z tego
# samego najnowszego ruchu per (candidate, job) — bez dodatkowego zapytania. ────


async def _get_user_name(user_id: int) -> str | None:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        return (
            await db.execute(select(User.name).where(User.id == user_id))
        ).scalar_one_or_none()


def _rec_for_job(item: dict, job_id: int) -> dict | None:
    """Find this candidate's active_recruitments entry for a given job."""
    for rec in item.get("active_recruitments") or []:
        if rec.get("job_id") == job_id:
            return rec
    return None


@pytest.mark.asyncio
async def test_active_recruitments_includes_current_stage_mover(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`include_active_recruitments=true` annotates each recruitment with KTO
    (`moved_by_name`) and KIEDY (`moved_at`) the candidate landed on its current
    stage — the data behind the list „Rekrutacje" popover."""
    job_id = await _seed_job()
    mover_a = await _seed_user()
    mover_name = await _get_user_name(mover_a)
    cand = await _seed_candidate(name_suffix="-MOVER")
    moved_at = datetime(2026, 5, 15, 9, 30, tzinfo=timezone.utc)
    await _seed_stage(cand, job_id, "verified", moved_at=moved_at, moved_by=mover_a)
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=verified"
            "&include_active_recruitments=true&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        item = next((it for it in r.json()["items"] if it["id"] == cand), None)
        assert item is not None, "seeded candidate missing from response"
        rec = _rec_for_job(item, job_id)
        assert rec is not None, "active recruitment for seeded job missing"
        assert rec["stage"] == "verified"
        assert rec["moved_by_name"] == mover_name
        assert rec["moved_at"] is not None
        assert rec["moved_at"].startswith("2026-05-15")
    finally:
        await _cleanup(
            candidate_ids=[cand], job_ids=[job_id], user_ids=[mover_a]
        )


@pytest.mark.asyncio
async def test_active_recruitments_mover_null_for_system_import(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A move with no `moved_by` (Traffit import / system) yields
    `moved_by_name=None` but still reports `moved_at` — the UI degrades to
    „Przeniesiono · <data>" without crashing."""
    job_id = await _seed_job()
    cand = await _seed_candidate(name_suffix="-SYS")
    moved_at = datetime(2026, 4, 1, 8, 0, tzinfo=timezone.utc)
    await _seed_stage(cand, job_id, "screening", moved_at=moved_at, moved_by=None)
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=screening"
            "&include_active_recruitments=true&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        item = next((it for it in r.json()["items"] if it["id"] == cand), None)
        assert item is not None
        rec = _rec_for_job(item, job_id)
        assert rec is not None
        assert rec["moved_by_name"] is None
        assert rec["moved_at"] is not None
    finally:
        await _cleanup(candidate_ids=[cand], job_ids=[job_id])


@pytest.mark.asyncio
async def test_active_recruitments_mover_reflects_latest_move(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Attribution tracks the LATEST move per (candidate, job): A verifies, then
    B advances to interview — the active recruitment must report stage=interview
    moved by B, not the earlier verify by A."""
    job_id = await _seed_job()
    mover_a = await _seed_user()
    mover_b = await _seed_user()
    name_b = await _get_user_name(mover_b)
    cand = await _seed_candidate(name_suffix="-LATEST")
    base = datetime(2026, 5, 10, 12, 0, tzinfo=timezone.utc)
    await _seed_stage(cand, job_id, "verified", moved_at=base, moved_by=mover_a)
    await _seed_stage(
        cand,
        job_id,
        "interview",
        moved_at=base + timedelta(days=3),
        moved_by=mover_b,
    )
    try:
        r = await app_client.get(
            "/api/candidates?include_active_recruitments=true&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        item = next((it for it in r.json()["items"] if it["id"] == cand), None)
        assert item is not None
        rec = _rec_for_job(item, job_id)
        assert rec is not None
        assert rec["stage"] == "interview"
        assert rec["moved_by_name"] == name_b
        assert rec["moved_at"].startswith("2026-05-13")
    finally:
        await _cleanup(
            candidate_ids=[cand],
            job_ids=[job_id],
            user_ids=[mover_a, mover_b],
        )
