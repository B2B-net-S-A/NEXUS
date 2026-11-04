"""Zapisany debrief jest widoczny (04.10.2026).

Sandra zapisała w debriefie, że kandydat chce jednak 125 zł/h. Pole „Warunek”
nie trafiało nigdzie: kalendarz pokazywał „debrief zapisany”, dok osoby tracił
przycisk, profil pokazywał tylko pola starego formularza, a dzwonek do DL nie
niósł warunku. Te testy pilnują, że warunek i pytania klienta wychodzą na
każdą z tych powierzchni oraz że debrief przyjmuje 30 pytań.
"""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.api.interview_cycle import MAX_DEBRIEF_QUESTIONS
from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from app.services.interview_cycle import interview_badges_for_job
from app.services.jarvis.tools import DEBRIEF_MAX_QUESTIONS
from tests.test_interview_cycle import _client_interview, _job_with_candidate, _user


def test_jarvis_debrief_limit_mirrors_the_api() -> None:
    assert MAX_DEBRIEF_QUESTIONS == 30
    assert DEBRIEF_MAX_QUESTIONS == MAX_DEBRIEF_QUESTIONS


async def _pair():
    rec_id, rec_h = await _user(UserRole.recruiter)
    dl_id, _ = await _user(UserRole.delivery_lead)
    job_id, cand_id, client_id = await _job_with_candidate(
        recruiter_id=rec_id, dl_id=dl_id
    )
    event_id = await _client_interview(
        owner_id=rec_id,
        cand_id=cand_id,
        job_id=job_id,
        client_id=client_id,
        ended_min_ago=10,
    )
    return rec_id, rec_h, dl_id, job_id, cand_id, event_id


def _payload(questions: list[str]) -> dict:
    return {
        "outcome": "good",
        "candidate_comment": "Projekt mu się podoba",
        "questions": questions,
        "offer_acceptance": "likely",
        "acceptance_condition": "Chce jednak 125 zł/h",
    }


async def test_debrief_accepts_thirty_questions_and_refuses_thirty_one(
    app_client: AsyncClient,
):
    _, rec_h, _, _, _, event_id = await _pair()
    url = f"/api/interview-cycle/events/{event_id}/debrief"

    too_many = await app_client.put(
        url, headers=rec_h, json=_payload([f"Pytanie {i}" for i in range(31)])
    )
    assert too_many.status_code == 422, too_many.text

    ok = await app_client.put(
        url, headers=rec_h, json=_payload([f"Pytanie {i}" for i in range(30)])
    )
    assert ok.status_code == 200, ok.text
    assert len(ok.json()["questions"]) == 30


async def test_saved_debrief_reaches_dl_bell_calendar_board_and_profile(
    app_client: AsyncClient,
):
    rec_id, rec_h, dl_id, job_id, cand_id, event_id = await _pair()
    saved = await app_client.put(
        f"/api/interview-cycle/events/{event_id}/debrief",
        headers=rec_h,
        json=_payload(["Jak testujesz trwałość danych?", "Kiedy @Transactional?"]),
    )
    assert saved.status_code == 200, saved.text

    # Dzwonek DL niesie warunek kandydata.
    async with AsyncSessionLocal() as db:
        note = (
            await db.execute(
                select(Notification).where(
                    Notification.user_id == dl_id,
                    Notification.notification_type
                    == NotificationType.interview_debrief_saved,
                    Notification.related_entity_id == event_id,
                )
            )
        ).scalar_one()
        assert "Warunek: Chce jednak 125 zł/h" in note.message

        # Odznaka karty na Tablicy (dok osoby) ma podsumowanie debriefu.
        badges = await interview_badges_for_job(
            db, job_id=job_id, candidate_ids=[cand_id]
        )
    debrief = badges[cand_id]["debrief"]
    assert debrief["outcome"] == "good"
    assert debrief["offer_acceptance"] == "likely"
    assert debrief["acceptance_condition"] == "Chce jednak 125 zł/h"
    assert debrief["candidate_comment"] == "Projekt mu się podoba"
    assert debrief["questions_count"] == 2

    # Ekran „Rozmowy u klienta” — ten sam skrót.
    overview = await app_client.get("/api/interview-cycle?scope=mine", headers=rec_h)
    item = next(i for i in overview.json()["items"] if i["candidate_id"] == cand_id)
    assert item["debrief"]["acceptance_condition"] == "Chce jednak 125 zł/h"
    assert item["debrief"]["questions_count"] == 2

    # Profil → Rekrutacje → „Feedback po rozmowach”.
    listed = await app_client.get(
        f"/api/interview-feedback?candidate_id={cand_id}", headers=rec_h
    )
    assert listed.status_code == 200, listed.text
    row = next(r for r in listed.json() if r["calendar_event_id"] == event_id)
    assert row["acceptance_condition"] == "Chce jednak 125 zł/h"
    assert row["offer_acceptance"] == "likely"
    assert row["no_client_questions"] is False
    assert row["author_name"] and row["author_name"].startswith("Cycle recruiter")
    assert row["calendar_event_start"] is not None
    assert row["updated_at"] is not None
