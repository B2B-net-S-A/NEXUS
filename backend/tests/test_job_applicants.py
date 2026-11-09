"""Wszyscy aplikujący na ogłoszenie i „aplikował na …” (07.11.2026)."""

from __future__ import annotations

import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.services.job_applicants import channel_label
from tests.test_pipeline_membership_gate import (
    _seed_candidate,
    _seed_job,
    _seed_recruiter,
)
from tests.test_portal_application import _place, _posting


def test_channel_label():
    from app.models.candidate_source_event import SourceChannel

    assert channel_label(SourceChannel.posting, "jjit") == "JustJoin.IT"
    assert channel_label(SourceChannel.career_link_job, "justjoinit") == "JustJoin.IT"
    assert channel_label(SourceChannel.career_link_job, None) == "Strona kariery"
    assert channel_label(SourceChannel.posting, None) == "Ogłoszenie"


async def _career_application(candidate_id: int, job_id: int) -> None:
    from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSourceEvent(
                candidate_id=candidate_id,
                job_id=job_id,
                channel=SourceChannel.career_link_job,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_applicants_list_and_applied_to(app_client):
    headers, uid = await _seed_recruiter(app_client)
    job_id, _ = await _seed_job(owner_id=uid)
    other_job, _ = await _seed_job(owner_id=uid)
    in_job = await _seed_candidate()
    outside = await _seed_candidate()
    ad_id = str(uuid.uuid4())
    await _posting(job_id, ad_id)
    assert (await _place(in_job, ad_id=ad_id)).outcome == "added"
    await _career_application(outside, job_id)
    await _career_application(in_job, other_job)

    resp = await app_client.get(f"/api/jobs/{job_id}/applicants", headers=headers)

    assert resp.status_code == 200, resp.text
    rows = {r["candidate_id"]: r for r in resp.json()["items"]}
    assert rows[in_job]["in_job"] is True and rows[in_job]["stage"] == "new"
    assert rows[in_job]["channel"] == "JustJoin.IT"
    assert rows[outside]["in_job"] is False
    assert rows[outside]["channel"] == "Strona kariery"

    facts = await app_client.get(
        f"/api/jobs/{job_id}/proposal-facts",
        params={"candidate_ids": [in_job]},
        headers=headers,
    )
    assert facts.status_code == 200, facts.text
    applied = facts.json()["items"][0]["applied_to"]
    assert [a["job_id"] for a in applied] == [other_job]
