"""Pytania pod rekrutacją = zadane na rozmowach w TEJ rekrutacji (02.11.2026).

Zgłoszenie: pod każdą rekrutacją klienta stała ta sama lista 50 najnowszych
pytań całego klienta, więc przy Project Managerze wisiały pytania z Javy
i nie było wiadomo, o co pytano naprawdę. Te testy pilnują, że:

* ``?job_id=`` zwraca wyłącznie pytania z debriefów tej rekrutacji i przypięcia
  importu Excela do tej rekrutacji;
* przypięcie przez człowieka albo kopia z szablonu nie udają „zadano na rozmowie”;
* ``?job_id=&scope=client`` to pełna lista klienta z rekrutacją przy pytaniu,
  a poprawiony debrief znika z rekrutacji, w której pytania jednak nie było.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.interview_question import (
    InterviewQuestion,
    InterviewQuestionSource,
    JobQuestion,
    JobQuestionAddedBySource,
)
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole

URL = "/api/interview-cycle/client-questions"


async def _admin() -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"asked-{tag}@example.com",
            password_hash=hash_password(f"As7ed_{tag}!pw"),
            name=f"Asked {tag}",
            role=UserRole.admin,
            roles=[UserRole.admin.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    token = create_access_token(uid, "admin", roles=["admin"])
    return uid, {"Authorization": f"Bearer {token}"}


async def _world() -> dict[str, int]:
    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Asked-{tag}")
        db.add(client)
        await db.flush()
        java = Job(
            title=f"Java Developer {tag}",
            status=JobStatus.published,
            client_id=client.id,
        )
        pm = Job(
            title=f"Project Manager {tag}",
            status=JobStatus.published,
            client_id=client.id,
        )
        cand = Candidate(
            name="Ewa",
            lastname=f"Pytania-{tag}",
            email=f"asked-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([java, pm, cand])
        await db.commit()
        return {
            "client": client.id,
            "java": java.id,
            "pm": pm.id,
            "cand": cand.id,
        }


async def _debrief(
    api: AsyncClient,
    headers: dict[str, str],
    w: dict[str, int],
    job_id: int,
    questions: list[str],
) -> int:
    start = datetime.now(timezone.utc) - timedelta(hours=2)
    async with AsyncSessionLocal() as db:
        event = CalendarEvent(
            title="Rozmowa u klienta",
            event_type=EventType.client_interview,
            start_time=start,
            end_time=start + timedelta(hours=1),
            status=EventStatus.completed,
            candidate_id=w["cand"],
            job_id=job_id,
            client_id=w["client"],
            attendees=[],
        )
        db.add(event)
        await db.commit()
        event_id = event.id
    await _put_debrief(api, headers, event_id, questions)
    return event_id


async def _put_debrief(
    api: AsyncClient, headers: dict[str, str], event_id: int, questions: list[str]
) -> None:
    saved = await api.put(
        f"/api/interview-cycle/events/{event_id}/debrief",
        headers=headers,
        json={"outcome": "good", "offer_acceptance": "yes", "questions": questions},
    )
    assert saved.status_code == 200, saved.text


async def _bank_question(
    client_id: int,
    text: str,
    *,
    source: InterviewQuestionSource = InterviewQuestionSource.legacy_import,
) -> int:
    from app.services.client_questions_asked import question_hash

    async with AsyncSessionLocal() as db:
        question = InterviewQuestion(
            text=text,
            client_id=client_id,
            source=source,
            normalized_text_hash=question_hash(text),
            skill_tags=[],
        )
        db.add(question)
        await db.commit()
        return question.id


async def _pin(job_id: int, question_id: int, *, user_id: int | None) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            JobQuestion(
                job_id=job_id,
                question_id=question_id,
                is_pinned=True,
                added_by_source=JobQuestionAddedBySource.manual,
                added_by_user_id=user_id,
            )
        )
        await db.commit()


async def _texts(api: AsyncClient, headers: dict[str, str], job_id: int) -> set[str]:
    resp = await api.get(f"{URL}?job_id={job_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return {q["text"] for q in resp.json()}


async def test_job_list_has_only_questions_asked_in_this_recruitment(
    app_client: AsyncClient,
):
    _, headers = await _admin()
    w = await _world()
    await _debrief(app_client, headers, w, w["java"], ["Transakcje w Spring"])
    await _debrief(app_client, headers, w, w["pm"], ["Jak prowadzisz retro?"])

    assert await _texts(app_client, headers, w["java"]) == {"Transakcje w Spring"}
    assert await _texts(app_client, headers, w["pm"]) == {"Jak prowadzisz retro?"}


async def test_recruitment_without_debriefs_has_empty_list(app_client: AsyncClient):
    _, headers = await _admin()
    w = await _world()
    await _debrief(app_client, headers, w, w["java"], ["Transakcje w Spring"])

    assert await _texts(app_client, headers, w["pm"]) == set()


async def test_excel_import_pin_counts_but_human_pin_does_not(app_client: AsyncClient):
    """Przypięcie importu (bez człowieka) to pytanie z tej rekrutacji w Excelu.
    Pin z Bazy pytań i kopia z szablonu mówią tylko „warto zapytać”."""
    user_id, headers = await _admin()
    w = await _world()
    excel = await _bank_question(w["client"], "Pytanie z Excela o tę rolę")
    by_hand = await _bank_question(w["client"], "Pytanie przypięte ręcznie")
    copied = await _bank_question(
        w["client"],
        "Pytanie skopiowane z szablonu",
        source=InterviewQuestionSource.client_debrief,
    )
    await _pin(w["pm"], excel, user_id=None)
    await _pin(w["pm"], by_hand, user_id=user_id)
    await _pin(w["pm"], copied, user_id=user_id)

    assert await _texts(app_client, headers, w["pm"]) == {"Pytanie z Excela o tę rolę"}
    assert await _texts(app_client, headers, w["java"]) == set()


async def test_corrected_debrief_removes_question_from_recruitment(
    app_client: AsyncClient,
):
    _, headers = await _admin()
    w = await _world()
    event_id = await _debrief(
        app_client,
        headers,
        w,
        w["java"],
        ["Pomyłka w debriefie", "Transakcje w Spring"],
    )

    await _put_debrief(app_client, headers, event_id, ["Transakcje w Spring"])

    assert await _texts(app_client, headers, w["java"]) == {"Transakcje w Spring"}


async def test_question_asked_in_two_recruitments_shows_under_both(
    app_client: AsyncClient,
):
    _, headers = await _admin()
    w = await _world()
    await _debrief(app_client, headers, w, w["java"], ["Opowiedz o sobie"])
    await _debrief(app_client, headers, w, w["pm"], ["  opowiedz   o SOBIE "])

    assert await _texts(app_client, headers, w["java"]) == {"Opowiedz o sobie"}
    assert await _texts(app_client, headers, w["pm"]) == {"Opowiedz o sobie"}


async def test_client_scope_lists_everything_with_recruitment(app_client: AsyncClient):
    _, headers = await _admin()
    w = await _world()
    await _debrief(app_client, headers, w, w["java"], ["Transakcje w Spring"])
    await _debrief(app_client, headers, w, w["pm"], ["Jak prowadzisz retro?"])
    other = await _world()
    await _debrief(
        app_client, headers, other, other["java"], ["Pytanie innego klienta"]
    )
    # Archiwum nie wpada do „wszystkich”: ma własną sekcję po technologiach roli.
    await _bank_question(w["client"], "Pytanie z archiwum")

    resp = await app_client.get(
        f"{URL}?job_id={w['pm']}&scope=client&limit=500", headers=headers
    )

    assert resp.status_code == 200, resp.text
    by_text = {q["text"]: [j["id"] for j in q["jobs"]] for q in resp.json()}
    assert by_text == {
        "Transakcje w Spring": [w["java"]],
        "Jak prowadzisz retro?": [w["pm"]],
    }
