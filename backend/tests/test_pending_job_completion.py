"""Pulpit: rekrutacje do dokończenia i niedokończone formularze (04.10.2026).

Reguły bez bazy + `GET /api/board-tasks` z bazą (CI). Baza testowa jest
wspólna, więc asercje dotyczą wyłącznie wierszy założonych w teście.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_intake_form import JobIntakeForm
from app.models.user import UserRole
from app.services import board_tasks, pending_job_completion as svc
from tests._jarvis_helpers import make_user

# ── bez bazy ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("count", "phrase"),
    [
        (1, "1 rekrutacja czeka na dokończenie"),
        (3, "3 rekrutacje czekają na dokończenie"),
        (5, "5 rekrutacji czeka na dokończenie"),
        (12, "12 rekrutacji czeka na dokończenie"),
        (22, "22 rekrutacje czekają na dokończenie"),
    ],
)
def test_pending_jobs_phrase(count: int, phrase: str) -> None:
    assert svc.pending_jobs_phrase(count) == phrase


def test_digest_line_counts_pending_jobs() -> None:
    line = board_tasks.DigestLine(dl_review=1, pending_jobs=2)
    assert line.total == 3
    assert board_tasks.digest_message(line) == (
        "1 osoba czeka na Twój przegląd · 2 rekrutacje czekają na dokończenie"
    )


@pytest.mark.asyncio
async def test_digest_counts_without_board_tasks_still_carries_pending_jobs() -> None:
    lines = await board_tasks.digest_counts(
        None, board_tasks.BoardTaskSnapshot(tasks=[]), pending_jobs={7: 3, 8: 0}
    )
    assert lines == {7: board_tasks.DigestLine(pending_jobs=3)}


# ── z bazą ───────────────────────────────────────────────────────────────────


async def _jobs(dl_id: int, other_dl_id: int) -> dict[str, int]:
    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Dokończ {tag}")
        db.add(client)
        await db.flush()
        rows = {
            "draft_mine": Job(
                title=f"Szkic {tag}",
                client_id=client.id,
                status=JobStatus.draft,
                delivery_lead_id=dl_id,
            ),
            "draft_created_by_me": Job(
                title=f"Szkic autora {tag}",
                client_id=client.id,
                status=JobStatus.draft,
                created_by=dl_id,
            ),
            "not_handed_off": Job(
                title=f"Bez przekazania {tag}",
                client_id=client.id,
                status=JobStatus.published,
                is_open=False,
                delivery_lead_id=dl_id,
            ),
            "handed_off": Job(
                title=f"Przekazana {tag}",
                client_id=client.id,
                status=JobStatus.published,
                is_open=True,
                delivery_lead_id=dl_id,
            ),
            "traffit_archive": Job(
                title=f"Traffit {tag}",
                client_id=client.id,
                status=JobStatus.published,
                is_open=False,
                delivery_lead_id=dl_id,
                external_source="traffit",
                external_id=f"t-{tag}",
            ),
            "closed": Job(
                title=f"Zamknięta {tag}",
                client_id=client.id,
                status=JobStatus.closed,
                delivery_lead_id=dl_id,
            ),
            "draft_other_dl": Job(
                title=f"Cudzy szkic {tag}",
                client_id=client.id,
                status=JobStatus.draft,
                delivery_lead_id=other_dl_id,
            ),
        }
        db.add_all(rows.values())
        await db.commit()
        return {key: job.id for key, job in rows.items()}


def _pending_ids(body: dict) -> dict[int, str]:
    block = body.get("pending_jobs") or {"items": []}
    return {item["job_id"]: item["kind"] for item in block["items"]}


@pytest.mark.asyncio
async def test_delivery_lead_sees_own_drafts_and_unhanded_jobs(app_client) -> None:
    dl_id, dl = await make_user(UserRole.delivery_lead)
    other_id, _ = await make_user(UserRole.delivery_lead)
    ids = await _jobs(dl_id, other_id)

    resp = await app_client.get("/api/board-tasks", headers=dl)

    assert resp.status_code == 200, resp.text
    seen = _pending_ids(resp.json())
    assert seen.get(ids["draft_mine"]) == "legacy_draft"
    assert seen.get(ids["draft_created_by_me"]) == "legacy_draft"
    assert seen.get(ids["not_handed_off"]) == "published_not_handed_off"
    for key in ("handed_off", "traffit_archive", "closed", "draft_other_dl"):
        assert ids[key] not in seen, key
    item = next(
        i
        for i in resp.json()["pending_jobs"]["items"]
        if i["job_id"] == ids["draft_mine"]
    )
    assert item["title"].startswith("Szkic")
    assert item["client_name"].startswith("Dokończ")
    assert isinstance(item["missing"], list) and item["missing"]


@pytest.mark.asyncio
async def test_head_of_recruitment_sees_every_pending_job(app_client) -> None:
    dl_id, _ = await make_user(UserRole.delivery_lead)
    other_id, _ = await make_user(UserRole.delivery_lead)
    ids = await _jobs(dl_id, other_id)
    _, hor = await make_user(UserRole.head_of_recruitment)

    seen = _pending_ids((await app_client.get("/api/board-tasks", headers=hor)).json())

    assert ids["draft_other_dl"] in seen
    assert ids["draft_mine"] in seen


@pytest.mark.asyncio
async def test_recruiter_gets_no_pending_jobs(app_client) -> None:
    _, recruiter = await make_user(UserRole.recruiter)
    body = (await app_client.get("/api/board-tasks", headers=recruiter)).json()
    assert body["pending_jobs"] is None


@pytest.mark.asyncio
async def test_unfinished_forms_older_than_two_days_only(app_client) -> None:
    user_id, headers = await make_user(UserRole.delivery_lead)
    async with AsyncSessionLocal() as db:
        old = JobIntakeForm(user_id=user_id, label="stary formularz", form={})
        fresh = JobIntakeForm(user_id=user_id, label="świeży formularz", form={})
        db.add_all([old, fresh])
        await db.flush()
        await db.execute(
            text("UPDATE job_intake_forms SET updated_at = :t WHERE id = :i"),
            {"t": datetime.now(timezone.utc) - timedelta(days=3), "i": old.id},
        )
        await db.commit()
        old_id, fresh_id = old.id, fresh.id

    body = (await app_client.get("/api/board-tasks", headers=headers)).json()

    ids = {f["id"] for f in body["unfinished_forms"]}
    assert old_id in ids and fresh_id not in ids
    row = next(f for f in body["unfinished_forms"] if f["id"] == old_id)
    assert row["label"] == "stary formularz"
    assert set(row) == {"id", "label", "client_name", "updated_at"}


@pytest.mark.asyncio
async def test_digest_counts_follow_the_panel_visibility() -> None:
    dl_id, _ = await make_user(UserRole.delivery_lead)
    other_id, _ = await make_user(UserRole.delivery_lead)
    await _jobs(dl_id, other_id)
    async with AsyncSessionLocal() as db:
        counts = await svc.digest_counts(db)
    # DL: dwa szkice (DL-em i autorem) + jedna bez przekazania.
    assert counts[dl_id] == 3
    assert counts[other_id] == 1
