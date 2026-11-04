"""„Screening dla” — screening pod kilka rekrutacji w jednej rozmowie (14.10.2026, D3).

Kontrakty (baza):

- ``joint-context`` wymienia inne rekrutacje osoby: Nowi/Screening bez cudzej
  blokady = do wyboru; późniejszy etap i cudza blokada = z powodem; zamknięta
  rekrutacja i proces zamknięty — poza listą; bieżąca rekrutacja — poza listą;
- ``question-groups`` łączy to samo pytanie z dwóch rekrutacji;
- notatkę z rozmowy zakłada zapis pierwszej pary, a druga para wskazuje ją
  ``note_id`` — bez kopii; obca osoba, inny autor i stara notatka — 422;
- quick-view w panelu osoby pomija bieżącą rekrutację i podaje sumę.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import UserRole
from tests.test_interview_cycle import _user
from tests.test_screening_form import (
    DOCK_NOTE,
    URL,
    _dock_note,
    _payload,
    _sheet,
    _token,
    _world,
)


async def _same_person_in(
    w: dict, stage: PipelineStage, *, process=ProcessStatus.open
) -> dict:
    """Druga rekrutacja tej samej osoby (osobny świat, przepięty na kandydata ``w``)."""
    other = await _world(stage, process=process)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(CandidateStage)
            .where(CandidateStage.job_id == other["job_id"])
            .values(candidate_id=w["cand_id"])
        )
        await db.execute(
            update(RecruitmentProcess)
            .where(RecruitmentProcess.job_id == other["job_id"])
            .values(candidate_id=w["cand_id"])
        )
        await db.commit()
    return {**other, "cand_id": w["cand_id"]}


async def test_joint_context_lists_other_pairs_with_reasons(app_client: AsyncClient):
    w = await _world(PipelineStage.new)
    screening = await _same_person_in(w, PipelineStage.screening)
    later = await _same_person_in(w, PipelineStage.cv_sent)
    finished = await _same_person_in(
        w, PipelineStage.screening, process=ProcessStatus.closed
    )
    claimed = await _same_person_in(w, PipelineStage.new)
    holder_id, _ = await _user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(RecruitmentProcess)
            .where(RecruitmentProcess.job_id == claimed["job_id"])
            .values(
                claimed_by_user_id=holder_id,
                claimed_until=datetime.now(timezone.utc) + timedelta(hours=5),
            )
        )
        await db.commit()

    res = await app_client.get(
        f"{URL}/joint-context",
        params={"candidate_id": w["cand_id"], "job_id": w["job_id"]},
        headers=w["rec_h"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["anchor"]["job_id"] == w["job_id"]
    assert body["anchor"]["client_id"] is not None
    pairs = {p["job_id"]: p for p in body["pairs"]}
    assert w["job_id"] not in pairs
    assert finished["job_id"] not in pairs
    assert pairs[screening["job_id"]]["selectable"] is True
    assert pairs[screening["job_id"]]["board_column"] == "screening"
    assert pairs[screening["job_id"]]["verified_stage_def_id"] is not None
    assert pairs[later["job_id"]]["selectable"] is False
    assert pairs[later["job_id"]]["reason"] == "later_stage"
    assert pairs[claimed["job_id"]]["reason"] == "claimed"
    assert pairs[claimed["job_id"]]["claim"]["mine"] is False


async def test_joint_context_uses_client_display_names(app_client: AsyncClient):
    w = await _world(PipelineStage.new)
    other = await _same_person_in(w, PipelineStage.screening)
    async with AsyncSessionLocal() as db:
        for job_id, label in (
            (w["job_id"], "Kotwica NEXUS"),
            (other["job_id"], "Para NEXUS"),
        ):
            client_id = await db.scalar(select(Job.client_id).where(Job.id == job_id))
            await db.execute(
                update(Client).where(Client.id == client_id).values(display_name=label)
            )
        await db.commit()

    res = await app_client.get(
        f"{URL}/joint-context",
        params={"candidate_id": w["cand_id"], "job_id": w["job_id"]},
        headers=w["rec_h"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["anchor"]["client_name"] == "Kotwica NEXUS"
    assert [p["client_name"] for p in body["pairs"]] == ["Para NEXUS"]


async def test_question_groups_join_the_same_question(app_client: AsyncClient):
    w = await _world()
    other = await _world()
    res = await app_client.get(
        f"{URL}/question-groups",
        params=[("job_ids", w["job_id"]), ("job_ids", other["job_id"])],
        headers=w["rec_h"],
    )
    assert res.status_code == 200, res.text
    groups = res.json()["groups"]
    # Oba światy mają te same dwa pytania — dwie grupy po dwie rekrutacje.
    assert sorted(len(g) for g in groups) == [2, 2]
    assert {(m["job_id"], m["question_id"]) for m in groups[0]} == {
        (w["job_id"], "q1"),
        (other["job_id"], "q1"),
    }


async def test_question_groups_need_two_jobs(app_client: AsyncClient):
    w = await _world()
    res = await app_client.get(
        f"{URL}/question-groups", params={"job_ids": w["job_id"]}, headers=w["rec_h"]
    )
    assert res.status_code == 422


async def _put_with_note(client: AsyncClient, w: dict, note_id: int) -> object:
    return await client.put(
        URL,
        headers=w["rec_h"],
        json=_payload(
            w,
            expected=0,
            token=await _token(client, w),
            note_import={"text": DOCK_NOTE, "note_id": note_id},
            sheet=_sheet(q1="Kafka od 3 lat"),
        ),
    )


async def test_second_pair_links_the_note_of_the_first(
    app_client: AsyncClient, monkeypatch
):
    monkeypatch.setattr(settings, "RECOMMENDATION_CARD_ASSIST_ENABLED", True)
    w = await _world()
    other = await _same_person_in(w, PipelineStage.screening)
    other = {**other, "rec_h": w["rec_h"], "rec_id": w["rec_id"]}
    note_id = await _dock_note(w)

    first = await _put_with_note(app_client, w, note_id)
    assert first.status_code == 200, first.text
    second = await _put_with_note(app_client, other, note_id)
    assert second.status_code == 200, second.text
    assert second.json()["note_id"] == note_id
    async with AsyncSessionLocal() as db:
        notes = await db.scalar(
            select(func.count())
            .select_from(Note)
            .where(Note.candidate_id == w["cand_id"])
        )
    assert notes == 1


@pytest.mark.parametrize("case", ["other_author", "stale", "not_in_note_job"])
async def test_joint_note_is_refused_outside_its_conversation(
    app_client: AsyncClient, monkeypatch, case: str
):
    monkeypatch.setattr(settings, "RECOMMENDATION_CARD_ASSIST_ENABLED", True)
    w = await _world()
    other = await _same_person_in(w, PipelineStage.screening)
    other = {**other, "rec_h": w["rec_h"], "rec_id": w["rec_id"]}
    if case == "not_in_note_job":
        stranger = await _world()
        note_id = await _dock_note(w, job_id=stranger["job_id"])
    else:
        note_id = await _dock_note(
            w, author_id=w["dl_id"] if case == "other_author" else None
        )
    if case == "stale":
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(Note)
                .where(Note.id == note_id)
                .values(created_at=datetime.now(timezone.utc) - timedelta(hours=3))
            )
            await db.commit()

    res = await _put_with_note(app_client, other, note_id)
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["code"] == "SCREENING_FORM_INVALID"


async def test_quick_view_skips_the_current_job_and_counts_the_rest(
    app_client: AsyncClient,
):
    w = await _world(PipelineStage.new)
    others = [await _same_person_in(w, PipelineStage.screening) for _ in range(5)]
    res = await app_client.get(
        f"/api/candidates/{w['cand_id']}/quick-view",
        params={"exclude_job_id": w["job_id"]},
        headers=w["rec_h"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    ids = [r["job_id"] for r in body["current_recruitments"]]
    assert w["job_id"] not in ids
    assert len(ids) == 4
    assert set(ids) <= {o["job_id"] for o in others}
    assert body["current_recruitments_total"] == 5


async def test_joint_context_carries_client_reference(app_client: AsyncClient):
    """Numer u klienta przed tytułem, jak w nagłówku rekrutacji (22.10.2026)."""
    w = await _world(PipelineStage.new)
    other = await _same_person_in(w, PipelineStage.screening)
    async with AsyncSessionLocal() as db:
        for job_id, reference in (
            (w["job_id"], "42946"),
            (other["job_id"], "ZOB-2984"),
        ):
            await db.execute(
                update(Job).where(Job.id == job_id).values(client_reference=reference)
            )
        await db.commit()

    res = await app_client.get(
        f"{URL}/joint-context",
        params={"candidate_id": w["cand_id"], "job_id": w["job_id"]},
        headers=w["rec_h"],
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["anchor"]["client_reference"] == "42946"
    assert [p["client_reference"] for p in body["pairs"]] == ["ZOB-2984"]
