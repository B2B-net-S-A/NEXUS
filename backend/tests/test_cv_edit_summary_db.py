"""E3 na prawdziwej bazie: start z generatora → zatwierdzenie → wpis → odczyt tygodniowy."""

from __future__ import annotations

from datetime import timedelta
import json

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.job import Job
from app.services.cv_edit_summary import ACTION, START_HTML_KEY
from scripts.cv_edit_report import _load_weekly, period_bounds
from tests.test_candidate_stage_cv_branded import _seed_full_stage


@pytest.fixture(autouse=True)
def approved_content_review(monkeypatch):
    from unittest.mock import AsyncMock

    from app.services import cv_approval_review

    monkeypatch.setattr(
        cv_approval_review,
        "review_for_approval",
        AsyncMock(return_value={"status": "verified", "method": "test-review"}),
    )


async def _select_generated(client, headers, sid: int, cid: int, jid: int) -> dict:
    base = f"/api/candidates/stages/{sid}/cv/branded"
    initial = (await client.get(base, headers=headers)).json()
    async with AsyncSessionLocal() as db:
        source = CvGeneratedDocument(
            candidate_id=cid,
            job_id=jid,
            candidate_name="Synthetic",
            filename="selected.docx",
            status="ready",
            render_payload={
                "name": "Synthetic",
                "why_points": ["Siedem lat w analizie", "Migracje hurtowni"],
            },
        )
        db.add(source)
        await db.commit()
        generated_id = source.id
    choice = await client.post(
        base + "/select-generated",
        headers=headers,
        json={
            "expected_revision": initial["edit_revision"],
            "generated_document_id": generated_id,
        },
    )
    assert choice.status_code == 200, choice.text
    return choice.json()


async def _entries(sid: int) -> list[Activity]:
    async with AsyncSessionLocal() as db:
        csv_id = await db.scalar(
            select(CandidateStageCV.id).where(
                CandidateStageCV.candidate_stage_id == sid
            )
        )
        return list(
            (
                await db.scalars(
                    select(Activity)
                    .where(Activity.action == ACTION, Activity.entity_id == csv_id)
                    .order_by(Activity.id)
                )
            ).all()
        )


async def test_approval_after_select_generated_records_what_changed(
    app_client, app_auth_headers
):
    sid, cid, jid = await _seed_full_stage()
    selected = await _select_generated(app_client, app_auth_headers, sid, cid, jid)
    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.candidate_stage_id == sid)
        )
        assert csv.branded_render_metadata[START_HTML_KEY] == selected["content_html"]

    edited = selected["content_html"].replace("Siedem lat", "Osiem lat")
    approved = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
        json={"expected_revision": selected["edit_revision"], "content_html": edited},
    )
    assert approved.status_code == 200, approved.text

    (entry,) = await _entries(sid)
    assert entry.details["status"] == "changed"
    assert entry.details["changed_parts"] == ["why_points"]
    assert entry.details["parts"]["why_points"]["changed"] == 1
    assert entry.details["job_id"] == jid
    assert (
        entry.details["document_version_id"] == approved.json()["document_version_id"]
    )
    dumped = json.dumps(entry.details, ensure_ascii=False)
    assert (
        "Osiem" not in dumped and "Siedem" not in dumped and "Synthetic" not in dumped
    )

    feed = await app_client.get(
        "/api/activities/feed?limit=100", headers=app_auth_headers
    )
    assert feed.status_code == 200, feed.text
    assert ACTION not in {item["action"] for item in feed.json()}

    today = business_today()
    async with AsyncSessionLocal() as db:
        rows = await _load_weekly(db, *period_bounds(today - timedelta(days=7), today))
        client_name = await db.scalar(
            select(Client.name)
            .join(Job, Job.client_id == Client.id)
            .where(Job.id == jid)
        )
    mine = [row for row in rows if row.client == client_name]
    assert len(mine) == 1
    assert mine[0].status == "changed" and mine[0].changed_parts == ("why_points",)


async def test_untouched_approval_is_unchanged(app_client, app_auth_headers):
    sid, cid, jid = await _seed_full_stage()
    selected = await _select_generated(app_client, app_auth_headers, sid, cid, jid)
    approved = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
        json={
            "expected_revision": selected["edit_revision"],
            "content_html": selected["content_html"],
        },
    )
    assert approved.status_code == 200, approved.text
    (entry,) = await _entries(sid)
    assert entry.details["status"] == "unchanged" and entry.details["parts"] == {}


async def test_failed_entry_does_not_block_the_approval(
    app_client, app_auth_headers, monkeypatch
):
    from unittest.mock import Mock

    from app.services import cv_edit_summary

    monkeypatch.setattr(
        cv_edit_summary, "summarize_edits", Mock(side_effect=RuntimeError("boom"))
    )
    sid, cid, jid = await _seed_full_stage()
    selected = await _select_generated(app_client, app_auth_headers, sid, cid, jid)
    approved = await app_client.post(
        f"/api/candidates/stages/{sid}/cv/branded/finalize",
        headers=app_auth_headers,
        json={
            "expected_revision": selected["edit_revision"],
            "content_html": selected["content_html"],
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "finalized"
    assert await _entries(sid) == []
