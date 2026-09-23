"""Feedback z rozmowy: sekcja Pipeline i wiązanie z wydarzeniem (audyt 14.09.2026).

Dwa ustalenia P1 z audytu procesów/uprawnień:

* **F02** — router `/api/interview-feedback` stał za guardami ROLOWYMI
  (`RecruitmentReadAccess` / `RecruitmentAssessmentWriteAccess`), które nie
  czytają efektywnego dostępu do sekcji. Rekruter z sekcją `pipeline=none`
  (nadpisanie per użytkownik) nadal czytał i zapisywał feedback przez API.
  Teraz router ma `PIPELINE_SECTION_DEPENDENCIES`: `none` → 403 na odczyt
  i zapis, `read` → odczyt tak, zapis 403.

* **F01** — `POST` sprawdzał wyłącznie ISTNIENIE wydarzenia. Dowolny
  operacyjny użytkownik mógł podpiąć feedback pod cudze spotkanie (gasząc na
  nim `needs_attention`), a kandydat/rekrutacja z payloadu nie musiały mieć
  nic wspólnego z tym, kogo spotkanie dotyczy. Teraz: obce wydarzenie → 403
  PRZED jakimkolwiek zapisem, rozjazd kandydata/rekrutacji → 422, pusty
  `job_id` dziedziczy rekrutację wydarzenia i przechodzi bramkę członkostwa.

Testy HTTP na prawdziwej bazie (`app_client`); dane syntetyczne (uuid).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.section_permission import UserSectionOverride
from app.models.user import User, UserRole
from httpx import AsyncClient
from sqlalchemy import select

FEEDBACK = "/api/interview-feedback"
_BASE = datetime(2037, 3, 4, 10, 0, tzinfo=timezone.utc)


# ── seed ─────────────────────────────────────────────────────────────────────


async def _seed_user(
    role: UserRole = UserRole.recruiter, *, pipeline: str | None = None
) -> tuple[dict[str, str], int]:
    """Użytkownik z opcjonalnym nadpisaniem sekcji Pipeline (`none`/`read`)."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"fb-access-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Feedback"),
            name=f"Feedback {role.value} {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        if pipeline is not None:
            db.add(
                UserSectionOverride(
                    user_id=user.id, section="pipeline", access=pipeline
                )
            )
        await db.commit()
        user_id = user.id
    headers = {"Authorization": f"Bearer {create_access_token(user_id, role.value)}"}
    return headers, user_id


async def _seed_job(owner_id: int | None) -> int:
    """Rekrutacja; `owner_id` → `recruiter_id`, czyli członek zespołu."""
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"FbAccessClient-{tag}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        job = Job(
            title=f"FbAccessJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=owner_id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate, CandidateStatus

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Feedback",
            lastname=f"Access-{tag}",
            email=f"fb-cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)
        return candidate.id


async def _seed_event(
    *,
    owner_id: int,
    job_id: int | None = None,
    candidate_id: int | None = None,
    attendees: list[str] | None = None,
) -> int:
    """Rozmowa oflagowana przez eskalację T+2h (`needs_attention=True`)."""
    async with AsyncSessionLocal() as db:
        event = CalendarEvent(
            title=f"Rozmowa {uuid.uuid4().hex[:6]}",
            event_type=EventType.interview,
            start_time=_BASE,
            end_time=_BASE + timedelta(hours=1),
            attendees=list(attendees or []),
            created_by=owner_id,
            job_id=job_id,
            candidate_id=candidate_id,
            status=EventStatus.scheduled,
            needs_attention=True,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event.id


async def _seed_feedback_row(
    *, event_id: int, candidate_id: int, author_id: int
) -> int:
    """Wiersz zapisany wprost w bazie — jak feedback sprzed tej bramki."""
    async with AsyncSessionLocal() as db:
        row = InterviewFeedback(
            calendar_event_id=event_id,
            candidate_id=candidate_id,
            job_id=None,
            author_id=author_id,
            feedback_source=FeedbackSource.candidate_side,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _needs_attention(event_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        event = await db.get(CalendarEvent, event_id)
        assert event is not None
        return event.needs_attention


async def _feedback_count(event_id: int) -> int:
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(InterviewFeedback.id).where(
                InterviewFeedback.calendar_event_id == event_id
            )
        )
        return len(rows.all())


def _body(event_id: int, candidate_id: int, job_id: int | None = None) -> dict:
    return {
        "calendar_event_id": event_id,
        "candidate_id": candidate_id,
        "job_id": job_id,
        "feedback_source": "candidate_side",
        "overall_impression": 4,
    }


async def _own_world(
    pipeline: str | None = None,
) -> tuple[dict[str, str], int, int, int, int]:
    """Rekruter, jego rekrutacja, kandydat i JEGO wydarzenie z obojgiem."""
    headers, uid = await _seed_user(pipeline=pipeline)
    job_id = await _seed_job(owner_id=uid)
    candidate_id = await _seed_candidate()
    event_id = await _seed_event(owner_id=uid, job_id=job_id, candidate_id=candidate_id)
    return headers, uid, job_id, candidate_id, event_id


# ── F02: sekcja Pipeline ─────────────────────────────────────────────────────


async def test_pipeline_none_blocks_read_and_write(app_client: AsyncClient) -> None:
    headers, _uid, job_id, candidate_id, event_id = await _own_world(pipeline="none")

    listed = await app_client.get(FEEDBACK, headers=headers)
    assert listed.status_code == 403, listed.text
    assert listed.json()["detail"]["code"] == "section_access_denied"

    created = await app_client.post(
        FEEDBACK, json=_body(event_id, candidate_id, job_id), headers=headers
    )
    assert created.status_code == 403, created.text
    assert created.json()["detail"]["code"] == "section_access_denied"
    assert await _feedback_count(event_id) == 0
    assert await _needs_attention(event_id) is True


async def test_pipeline_read_allows_list_but_refuses_write(
    app_client: AsyncClient,
) -> None:
    headers, _uid, job_id, candidate_id, event_id = await _own_world(pipeline="read")

    listed = await app_client.get(FEEDBACK, headers=headers)
    assert listed.status_code == 200, listed.text

    created = await app_client.post(
        FEEDBACK, json=_body(event_id, candidate_id, job_id), headers=headers
    )
    assert created.status_code == 403, created.text
    assert created.json()["detail"]["code"] == "section_access_denied"
    assert await _feedback_count(event_id) == 0


# ── F01: wiązanie feedbacku z wydarzeniem ────────────────────────────────────


async def test_foreign_event_is_refused_before_any_write(
    app_client: AsyncClient,
) -> None:
    """Cudze spotkanie (autor inny, rekrutacja niedostępna) + `job_id=null`."""
    headers, _uid = await _seed_user()
    _other_headers, other_id = await _seed_user()
    foreign_job = await _seed_job(owner_id=None)
    candidate_id = await _seed_candidate()
    event_id = await _seed_event(
        owner_id=other_id, job_id=foreign_job, candidate_id=candidate_id
    )

    resp = await app_client.post(
        FEEDBACK, json=_body(event_id, candidate_id, None), headers=headers
    )
    assert resp.status_code == 403, resp.text
    assert "wydarzenia" in resp.json()["detail"]
    assert await _needs_attention(event_id) is True
    assert await _feedback_count(event_id) == 0


async def test_job_mismatch_with_event_is_refused(app_client: AsyncClient) -> None:
    """Własna rekrutacja w payloadzie, ale wydarzenie innej rekrutacji → 422."""
    headers, uid = await _seed_user()
    job_in_payload = await _seed_job(owner_id=uid)
    job_of_event = await _seed_job(owner_id=uid)
    candidate_id = await _seed_candidate()
    event_id = await _seed_event(
        owner_id=uid, job_id=job_of_event, candidate_id=candidate_id
    )

    resp = await app_client.post(
        FEEDBACK,
        json=_body(event_id, candidate_id, job_in_payload),
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert "Rekrutacja" in resp.json()["detail"]
    assert await _needs_attention(event_id) is True
    assert await _feedback_count(event_id) == 0


async def test_candidate_mismatch_with_event_is_refused(
    app_client: AsyncClient,
) -> None:
    headers, _uid, job_id, _candidate_id, event_id = await _own_world()
    other_candidate = await _seed_candidate()

    resp = await app_client.post(
        FEEDBACK, json=_body(event_id, other_candidate, job_id), headers=headers
    )
    assert resp.status_code == 422, resp.text
    assert "Kandydat" in resp.json()["detail"]
    assert await _needs_attention(event_id) is True
    assert await _feedback_count(event_id) == 0


async def test_inherited_job_outside_the_team_is_recorded(
    app_client: AsyncClient,
) -> None:
    """Własne wydarzenie, rekrutacja spoza zespołu — od 23.09.2026 feedback
    się zapisuje (decyzja Artura: rekrutację obsługuje każdy, bez
    przypisania). Rekrutację feedback dziedziczy z wydarzenia."""
    headers, uid = await _seed_user()
    foreign_job = await _seed_job(owner_id=None)
    candidate_id = await _seed_candidate()
    event_id = await _seed_event(
        owner_id=uid, job_id=foreign_job, candidate_id=candidate_id
    )

    resp = await app_client.post(
        FEEDBACK, json=_body(event_id, candidate_id, None), headers=headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["job_id"] == foreign_job
    assert await _feedback_count(event_id) == 1
    assert await _needs_attention(event_id) is False


async def test_attendee_of_someone_elses_event_records_feedback(
    app_client: AsyncClient,
) -> None:
    """Rekruter-uczestnik rozmowy zorganizowanej przez kogoś innego (np. DL)
    pisze z niej feedback — bramka to udział w spotkaniu, nie własność."""
    headers, uid = await _seed_user()
    _dl_headers, dl_id = await _seed_user(UserRole.delivery_lead)
    job_id = await _seed_job(owner_id=uid)
    candidate_id = await _seed_candidate()
    async with AsyncSessionLocal() as db:
        email = (await db.get(User, uid)).email
    event_id = await _seed_event(
        owner_id=dl_id, job_id=job_id, candidate_id=candidate_id, attendees=[email]
    )

    resp = await app_client.post(
        FEEDBACK, json=_body(event_id, candidate_id, None), headers=headers
    )
    assert resp.status_code == 201, resp.text
    assert await _needs_attention(event_id) is False


async def test_organizer_with_matching_data_records_feedback_and_clears_flag(
    app_client: AsyncClient,
) -> None:
    headers, _uid, job_id, candidate_id, event_id = await _own_world()

    resp = await app_client.post(
        FEEDBACK, json=_body(event_id, candidate_id, None), headers=headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # Pusty `job_id` dziedziczy rekrutację wydarzenia.
    assert body["job_id"] == job_id
    assert body["candidate_id"] == candidate_id
    assert await _needs_attention(event_id) is False
    assert await _feedback_count(event_id) == 1


async def test_patch_clears_flag_only_for_author_or_event_owner(
    app_client: AsyncClient,
) -> None:
    """DL poprawia cudzy feedback, ale nie gasi flagi na cudzym spotkaniu."""
    author_headers, author_id = await _seed_user()
    dl_headers, _dl_id = await _seed_user(UserRole.delivery_lead)
    candidate_id = await _seed_candidate()
    event_id = await _seed_event(owner_id=author_id, candidate_id=candidate_id)
    feedback_id = await _seed_feedback_row(
        event_id=event_id, candidate_id=candidate_id, author_id=author_id
    )

    by_dl = await app_client.patch(
        f"{FEEDBACK}/{feedback_id}", json={"concerns": "Uwaga DL"}, headers=dl_headers
    )
    assert by_dl.status_code == 200, by_dl.text
    assert by_dl.json()["concerns"] == "Uwaga DL"
    assert await _needs_attention(event_id) is True

    by_author = await app_client.patch(
        f"{FEEDBACK}/{feedback_id}",
        json={"concerns": "Uwaga autora"},
        headers=author_headers,
    )
    assert by_author.status_code == 200, by_author.text
    assert await _needs_attention(event_id) is False


async def test_saved_feedback_is_visible_on_the_event(app_client: AsyncClient) -> None:
    """Okno wydarzenia pokazuje „Edytuj feedback" zamiast „Uzupełnij" dopiero,
    gdy odpowiedź wydarzenia niesie `feedback_sources` (audyt 17.09.2026)."""
    headers, _uid, _job_id, candidate_id, event_id = await _own_world()

    before = await app_client.get(f"/api/calendar/events/{event_id}", headers=headers)
    assert before.status_code == 200, before.text
    assert before.json()["feedback_sources"] == []
    assert before.json()["needs_attention"] is True

    resp = await app_client.post(
        FEEDBACK, json=_body(event_id, candidate_id, None), headers=headers
    )
    assert resp.status_code == 201, resp.text

    after = await app_client.get(f"/api/calendar/events/{event_id}", headers=headers)
    assert after.status_code == 200, after.text
    assert after.json()["feedback_sources"] == ["candidate_side"]
    assert after.json()["needs_attention"] is False
