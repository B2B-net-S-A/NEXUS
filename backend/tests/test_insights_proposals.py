"""Raport „Propozycje AI” i poniedziałkowy skrót — ścieżka z bazą (CI).

Części czyste: ``test_proposal_feedback.py``.
"""

from datetime import datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from app.services import job_proposals as proposals
from app.services import proposals_digest
from tests.test_job_proposals import _REASON, _inbox, _user, _world

_URL = "/api/insights/proposals/outcomes"
_MONDAY = datetime(2026, 9, 28, 8, 0, tzinfo=timezone.utc)


async def _seed(job_id: int, candidate_ids: list[int], source: str) -> None:
    async with AsyncSessionLocal() as db:
        await proposals.upsert_proposals(
            db, job_id, [{"candidate_id": c} for c in candidate_ids], source
        )
        await db.commit()


async def _set_dl(job_id: int, dl_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job).where(Job.id == job_id).values(delivery_lead_id=dl_id)
        )
        await db.commit()


async def test_report_counts_decisions_and_scopes_the_delivery_lead(
    app_client: AsyncClient, app_auth_headers: dict
):
    dl_id, dl = await _user(UserRole.delivery_lead)
    recruiter_id, recruiter = await _user(UserRole.recruiter)
    own = await _world(people=3, recruiter_id=recruiter_id)
    other = await _world(people=1, recruiter_id=recruiter_id)
    await _set_dl(own["job_id"], dl_id)
    await _seed(own["job_id"], own["candidate_ids"], "full_base")
    await _seed(own["job_id"], own["candidate_ids"][:1], "new_cv")
    await _seed(other["job_id"], other["candidate_ids"], "job_board")

    first, second, _third = own["candidate_ids"]
    done = await app_client.post(
        f"{_inbox(own['job_id'])}/{first}/dismiss",
        json={"reason": "missing_critical"},
        headers=recruiter,
    )
    assert done.status_code == 200, done.text
    async with AsyncSessionLocal() as db:
        await proposals.mark_added(db, job_id=own["job_id"], candidate_ids=[second])
        await db.commit()

    # Rekruter nie ma raportu.
    refused = await app_client.get(_URL, headers=recruiter)
    assert refused.status_code == 403, refused.text

    as_dl = await app_client.get(_URL, params={"days": 7}, headers=dl)
    assert as_dl.status_code == 200, as_dl.text
    body = as_dl.json()
    assert body["scope"] == "delivery_lead"
    jobs = {j["job_id"]: j for j in body["jobs"]}
    assert other["job_id"] not in jobs
    row = jobs[own["job_id"]]
    assert (row["proposed"], row["added"], row["dismissed"], row["pending"]) == (
        3,
        1,
        1,
        1,
    )
    assert row["dismissed_by_reason"]["missing_critical"] == 1

    as_admin = await app_client.get(_URL, headers=app_auth_headers)
    assert as_admin.status_code == 200, as_admin.text
    admin_jobs = {j["job_id"] for j in as_admin.json()["jobs"]}
    assert {own["job_id"], other["job_id"]} <= admin_jobs
    assert as_admin.json()["scope"] == "organization"

    bad = await app_client.get(_URL, params={"days": 0}, headers=app_auth_headers)
    assert bad.status_code == 422


async def test_monday_digest_once_per_week_per_delivery_lead():
    dl_id, _ = await _user(UserRole.delivery_lead)
    world = await _world(people=2)
    await _set_dl(world["job_id"], dl_id)
    await _seed(world["job_id"], world["candidate_ids"], "full_base")

    for _ in range(2):
        async with AsyncSessionLocal() as db:
            await proposals_digest.send_pending_proposals_digest(db, _MONDAY)
            await db.commit()

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(Notification).where(
                    Notification.user_id == dl_id,
                    Notification.notification_type
                    == NotificationType.auto_match_proposals,
                )
            )
        ).all()
    assert len(rows) == 1
    assert rows[0].related_entity_type == proposals_digest.DIGEST_ENTITY_TYPE
    assert rows[0].related_entity_id == proposals_digest.week_key(_MONDAY)
    assert "2 propozycje czekają" in rows[0].title
    assert rows[0].link == f"/jobs/{world['job_id']}?tab=similar"


async def test_dismissed_proposals_do_not_count_in_the_digest():
    dl_id, _ = await _user(UserRole.delivery_lead)
    recruiter_id, _recruiter = await _user(UserRole.recruiter)
    world = await _world(people=1, recruiter_id=recruiter_id)
    await _set_dl(world["job_id"], dl_id)
    await _seed(world["job_id"], world["candidate_ids"], "full_base")
    async with AsyncSessionLocal() as db:
        await proposals.dismiss(
            db,
            job_id=world["job_id"],
            candidate_id=world["candidate_ids"][0],
            user_id=recruiter_id,
            reason=_REASON["reason"],
        )
        await db.commit()
        await proposals_digest.send_pending_proposals_digest(db, _MONDAY)
        await db.commit()
        count = len(
            (
                await db.scalars(
                    select(Notification.id).where(Notification.user_id == dl_id)
                )
            ).all()
        )
    assert count == 0
