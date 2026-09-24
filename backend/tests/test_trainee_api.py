"""Praktykant — lista telefonów przez API na prawdziwej bazie (0374).

Kontrakty (decyzje Artura 24.09.2026):

- praktykant widzi wyłącznie „Telefony na dziś” — każda inna trasa 403;
- zapis rozmowy: minimalna stawka B2B netto do stawki profilu, fakty
  i zgody w profilu, notatka i wiersz ``calls`` w historii;
- „Nie odbiera”: pierwsza próba zostawia pozycję otwartą, druga zamyka;
- pula nie bierze osób, do których telefon coś psuje (czarna lista, umowa
  u nas, „tylko etat”, niedawny telefon praktykanta, „niezainteresowany”);
- awans z panelu zmienia rolę i kończy program.

Baza testowa jest wspólna i nieczyszczona — każdy test zakłada własne dane
(unikalne nazwy umiejętności) i asertuje wyłącznie po nich.
"""

from __future__ import annotations

import os
import uuid
from datetime import timedelta

import pytest

needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


def _headers(user_id: int, role: str) -> dict:
    from app.core.security import create_access_token

    return {
        "Authorization": f"Bearer {create_access_token(subject=user_id, role=role)}"
    }


async def _user(db, role: str):
    from app.models.user import User, UserRole

    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"trainee-{marker}@example.com",
        name=f"Praktykant {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
        profile_completed=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _world(db, *, skill: str):
    """Dwie opublikowane rekrutacje wymagające ``skill`` + praktykant z programem."""
    from app.core.scheduling import business_today
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.trainee import TraineeProgram

    client = Client(name=f"trainee-client-{uuid.uuid4().hex[:8]}")
    db.add(client)
    await db.flush()
    jobs = []
    for n in range(2):
        job = Job(
            title=f"{skill} developer {n}",
            client_id=client.id,
            status=JobStatus.published,
            must_skills=[skill],
        )
        db.add(job)
        jobs.append(job)
    trainee = await _user(db, "trainee")
    db.add(
        TraineeProgram(
            user_id=trainee.id,
            start_date=business_today() - timedelta(days=14),
            daily_list_size=50,
        )
    )
    await db.flush()
    return trainee, jobs


async def _candidate(db, *, skill: str, **kw):
    from app.models.candidate import Candidate

    cand = Candidate(
        name="Tomasz",
        lastname=f"Tr{uuid.uuid4().hex[:8]}",
        phone=f"+48 6{uuid.uuid4().int % 10**8:08d}",
        skills=[{"name": skill}],
        **kw,
    )
    db.add(cand)
    await db.flush()
    return cand


async def _list_with(db, trainee, candidates):
    """Lista na dziś złożona z konkretnych osób (pula całej bazy jest wspólna)."""
    from app.core.scheduling import business_today
    from app.services import trainee_call_list as lists
    from app.services.trainee_rules import Demand

    ranked = [
        lists.RankedCandidate(
            candidate_id=c.id,
            competence_category_id=None,
            demand=Demand(fits=2, open_fits=2, stack=("Skill",), job_ids=()),
            missing=("b2b",),
            stack_display=("Skill",),
        )
        for c in candidates
    ]
    programs = await lists.active_programs(db, today=business_today())
    mine = [p for p in programs if p.user_id == trainee.id]
    await lists.generate_lists(db, mine, today=business_today(), ranked=ranked)


def _skill() -> str:
    return f"trainskill{uuid.uuid4().hex[:8]}"


@needs_db
@pytest.mark.asyncio
async def test_trainee_is_confined_to_own_screen(app_client) -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        trainee = await _user(db, "trainee")
        recruiter = await _user(db, "recruiter")
        await db.commit()
        trainee_id, recruiter_id = trainee.id, recruiter.id

    resp = await app_client.get(
        "/api/candidates", headers=_headers(trainee_id, "trainee")
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "trainee_restricted"

    resp = await app_client.get(
        "/api/trainee/today", headers=_headers(recruiter_id, "recruiter")
    )
    assert resp.status_code == 403

    resp = await app_client.get("/api/auth/me", headers=_headers(trainee_id, "trainee"))
    assert resp.status_code == 200


@needs_db
@pytest.mark.asyncio
async def test_trainee_cannot_open_the_event_socket() -> None:
    from app.api.ws import _authenticate_ws_token
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token

    async with AsyncSessionLocal() as db:
        trainee = await _user(db, "trainee")
        recruiter = await _user(db, "recruiter")
        await db.commit()
        trainee_id, recruiter_id = trainee.id, recruiter.id

    assert (
        await _authenticate_ws_token(
            create_access_token(subject=trainee_id, role="trainee")
        )
        is None
    )
    assert (
        await _authenticate_ws_token(
            create_access_token(subject=recruiter_id, role="recruiter")
        )
        is not None
    )


@needs_db
@pytest.mark.asyncio
async def test_pool_ranks_demand_and_skips_unsafe_people() -> None:
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.candidate import CandidateStatus
    from app.models.contract import Contract, ContractStatus
    from app.services import trainee_call_list as lists
    from app.services.job_similarity import reset_pool_cache

    # Prawdziwa technologia z taksonomii: przy wczytanej taksonomii (start
    # aplikacji w innym teście) wymyślona nazwa odpadłaby z must-have obu stron.
    skill = "Java"
    async with AsyncSessionLocal() as db:
        trainee, jobs = await _world(db, skill=skill)
        good = await _candidate(db, skill=skill)
        blacklisted = await _candidate(
            db, skill=skill, status=CandidateStatus.blacklisted
        )
        employment_only = await _candidate(
            db, skill=skill, b2b_willingness="employment_only"
        )
        no_phone = await _candidate(db, skill=skill)
        no_phone.phone = None
        employed = await _candidate(db, skill=skill)
        db.add(
            Contract(
                candidate_id=employed.id,
                client_id=jobs[0].client_id,
                status=ContractStatus.active,
            )
        )
        await db.commit()
        reset_pool_cache()
        rules = await lists.load_rules(db)
        ranked = await lists.rank_pool(db, rules, today=business_today())

    by_id = {item.candidate_id: item for item in ranked}
    assert good.id in by_id
    assert by_id[good.id].demand.fits >= 2
    assert by_id[good.id].demand.open_fits >= 2
    for excluded in (blacklisted, employment_only, no_phone, employed):
        assert excluded.id not in by_id


@needs_db
@pytest.mark.asyncio
async def test_save_call_writes_minimum_rate_facts_note_and_call(app_client) -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.call import Call
    from app.models.candidate import Candidate
    from app.models.note import Note

    skill = _skill()
    async with AsyncSessionLocal() as db:
        trainee, _ = await _world(db, skill=skill)
        cand = await _candidate(db, skill=skill)
        await _list_with(db, trainee, [cand])
        await db.commit()
        trainee_id, cand_id = trainee.id, cand.id

    headers = _headers(trainee_id, "trainee")
    today = await app_client.get("/api/trainee/today", headers=headers)
    assert today.status_code == 200, today.text
    body = today.json()
    assert body["status"] == "ready"
    item = next(i for i in body["items"] if i["candidate_id"] == cand_id)
    assert item["phone"]

    resp = await app_client.post(
        f"/api/trainee/items/{item['id']}/call",
        headers=headers,
        json={
            "b2b_willingness": "would_switch",
            "min_rate": {"value": 1200, "unit": "day"},
            "accepts_below_min_rate": True,
            "remote_modes": ["hybrid"],
            "max_onsite_days": 2,
            "accepts_more_office_days": False,
            "office_cities": ["Kraków"],
            "work_time_preference": "also_part_time",
            "availability": "within_1m",
            "open_to_offers": "yes",
            "wants": "Java, bez bankowości",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["item"]["outcome"] == "call"

    again = await app_client.post(
        f"/api/trainee/items/{item['id']}/call",
        headers=headers,
        json={"b2b_willingness": "b2b"},
    )
    assert again.status_code == 409

    async with AsyncSessionLocal() as db:
        saved = await db.get(Candidate, cand_id)
        assert float(saved.expected_rate_hourly) == 150.0
        assert saved.b2b_willingness == "would_switch"
        assert saved.accepts_below_min_rate is True
        assert saved.accepts_more_office_days is False
        assert saved.work_time_preference == "also_part_time"
        assert saved.max_onsite_days_per_week == 2
        assert saved.call_facts_verified_by_user_id == trainee_id
        assert saved.cv_extracted_data.get("_manual_override_rate") is True
        note = await db.scalar(
            select(Note).where(
                Note.candidate_id == cand_id, Note.external_source == "trainee_call"
            )
        )
        assert note is not None and "Minimalna stawka" in note.content
        call = await db.scalar(
            select(Call).where(Call.candidate_id == cand_id, Call.user_id == trainee_id)
        )
        assert call is not None and call.contact_outcome == "connected"


@needs_db
@pytest.mark.asyncio
async def test_no_answer_twice_closes_and_other_trainee_gets_404(app_client) -> None:
    from app.core.database import AsyncSessionLocal

    skill = _skill()
    async with AsyncSessionLocal() as db:
        trainee, _ = await _world(db, skill=skill)
        other = await _user(db, "trainee")
        cand = await _candidate(db, skill=skill)
        await _list_with(db, trainee, [cand])
        await db.commit()
        trainee_id, other_id, cand_id = trainee.id, other.id, cand.id

    headers = _headers(trainee_id, "trainee")
    body = (await app_client.get("/api/trainee/today", headers=headers)).json()
    item_id = next(i["id"] for i in body["items"] if i["candidate_id"] == cand_id)

    foreign = await app_client.post(
        f"/api/trainee/items/{item_id}/outcome",
        headers=_headers(other_id, "trainee"),
        json={"outcome": "noanswer"},
    )
    assert foreign.status_code == 404

    first = await app_client.post(
        f"/api/trainee/items/{item_id}/outcome",
        headers=headers,
        json={"outcome": "noanswer"},
    )
    assert first.status_code == 200, first.text
    assert first.json()["item"]["outcome"] is None
    assert first.json()["item"]["retry_after"]

    second = await app_client.post(
        f"/api/trainee/items/{item_id}/outcome",
        headers=headers,
        json={"outcome": "noanswer"},
    )
    assert second.json()["item"]["outcome"] == "noanswer"


@needs_db
@pytest.mark.asyncio
async def test_later_needs_a_future_workday(app_client) -> None:
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today

    skill = _skill()
    async with AsyncSessionLocal() as db:
        trainee, _ = await _world(db, skill=skill)
        cand = await _candidate(db, skill=skill)
        await _list_with(db, trainee, [cand])
        await db.commit()
        trainee_id, cand_id = trainee.id, cand.id

    headers = _headers(trainee_id, "trainee")
    body = (await app_client.get("/api/trainee/today", headers=headers)).json()
    item_id = next(i["id"] for i in body["items"] if i["candidate_id"] == cand_id)
    resp = await app_client.post(
        f"/api/trainee/items/{item_id}/outcome",
        headers=headers,
        json={"outcome": "later", "later_date": business_today().isoformat()},
    )
    assert resp.status_code == 422


@needs_db
@pytest.mark.asyncio
async def test_handover_creates_trainee_proposal(app_client) -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.job_proposal import JobProposal
    from app.services.job_similarity import reset_pool_cache

    skill = "Java"
    async with AsyncSessionLocal() as db:
        trainee, jobs = await _world(db, skill=skill)
        cand = await _candidate(db, skill=skill)
        await _list_with(db, trainee, [cand])
        await db.commit()
        trainee_id, cand_id, job_id = trainee.id, cand.id, jobs[0].id

    reset_pool_cache()
    headers = _headers(trainee_id, "trainee")
    body = (await app_client.get("/api/trainee/today", headers=headers)).json()
    item_id = next(i["id"] for i in body["items"] if i["candidate_id"] == cand_id)
    saved = await app_client.post(
        f"/api/trainee/items/{item_id}/call",
        headers=headers,
        json={"b2b_willingness": "b2b"},
    )
    assert saved.status_code == 200, saved.text
    open_jobs = await app_client.get(
        f"/api/trainee/items/{item_id}/open-jobs", headers=headers
    )
    assert job_id in {row["job_id"] for row in open_jobs.json()}
    resp = await app_client.post(
        f"/api/trainee/items/{item_id}/handover",
        headers=headers,
        json={"job_id": job_id, "note": "Szuka od listopada"},
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        proposal = await db.scalar(
            select(JobProposal).where(
                JobProposal.job_id == job_id,
                JobProposal.candidate_id == cand_id,
                JobProposal.source == "trainee",
            )
        )
        assert proposal is not None
        assert proposal.evidence["trainee"] == {
            "user_id": trainee_id,
            "note": "Szuka od listopada",
        }


@needs_db
@pytest.mark.asyncio
async def test_promotion_changes_role_and_ends_program(app_client) -> None:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.trainee import TraineeProgram
    from app.models.user import User, UserRole

    skill = _skill()
    async with AsyncSessionLocal() as db:
        trainee, _ = await _world(db, skill=skill)
        hor = await _user(db, "head_of_recruitment")
        await db.commit()
        trainee_id, hor_id = trainee.id, hor.id

    hor_headers = _headers(hor_id, "head_of_recruitment")
    overview = await app_client.get("/api/trainee/overview", headers=hor_headers)
    assert overview.status_code == 200, overview.text
    assert trainee_id in {row["user_id"] for row in overview.json()["trainees"]}

    resp = await app_client.post(
        f"/api/trainee/programs/{trainee_id}/decision",
        headers=hor_headers,
        json={"action": "promote", "role": "admin"},
    )
    assert resp.status_code == 422

    resp = await app_client.post(
        f"/api/trainee/programs/{trainee_id}/decision",
        headers=hor_headers,
        json={"action": "promote", "role": "sourcer", "add_to_my_people": True},
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        user = await db.get(User, trainee_id)
        assert user.role == UserRole.sourcer
        assert user.roles == ["sourcer"]
        program = await db.scalar(
            select(TraineeProgram).where(TraineeProgram.user_id == trainee_id)
        )
        assert program.status == "completed"
        assert program.decision == "promoted"


# ── Audyt 24.09.2026 ─────────────────────────────────────────────────────────


@needs_db
@pytest.mark.asyncio
async def test_handover_needs_a_call_today_and_reopens_a_dismissed_proposal(
    app_client,
) -> None:
    """M19: bez zapisanej rozmowy (np. „niezainteresowany”) nie ma przekazania;
    odrzucona wcześniej propozycja wraca do „Do przejrzenia”, a nie ginie."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.job_proposal import JobProposal
    from app.services.job_proposals import dismiss, upsert_proposals
    from app.services.job_similarity import reset_pool_cache

    skill = "Java"
    async with AsyncSessionLocal() as db:
        trainee, jobs = await _world(db, skill=skill)
        declined = await _candidate(db, skill=skill)
        talked = await _candidate(db, skill=skill)
        await _list_with(db, trainee, [declined, talked])
        job_id = jobs[0].id
        # Ta para była już zaproponowana i pominięta przez rekrutera.
        await upsert_proposals(
            db, job_id, [{"candidate_id": talked.id}], source="full_base"
        )
        await dismiss(db, job_id=job_id, candidate_id=talked.id, user_id=None)
        await db.commit()
        trainee_id, declined_id, talked_id = trainee.id, declined.id, talked.id

    reset_pool_cache()
    headers = _headers(trainee_id, "trainee")
    body = (await app_client.get("/api/trainee/today", headers=headers)).json()
    ids = {i["candidate_id"]: i["id"] for i in body["items"]}

    out = await app_client.post(
        f"/api/trainee/items/{ids[declined_id]}/outcome",
        headers=headers,
        json={"outcome": "declined"},
    )
    assert out.status_code == 200, out.text
    refused = await app_client.post(
        f"/api/trainee/items/{ids[declined_id]}/handover",
        headers=headers,
        json={"job_id": job_id},
    )
    assert refused.status_code == 409
    assert "rozmowę" in refused.json()["detail"]
    jobs_refused = await app_client.get(
        f"/api/trainee/items/{ids[declined_id]}/open-jobs", headers=headers
    )
    assert jobs_refused.status_code == 409

    open_item = await app_client.post(
        f"/api/trainee/items/{ids[talked_id]}/handover",
        headers=headers,
        json={"job_id": job_id},
    )
    assert open_item.status_code == 409  # jeszcze bez rozmowy

    saved = await app_client.post(
        f"/api/trainee/items/{ids[talked_id]}/call",
        headers=headers,
        json={"b2b_willingness": "b2b"},
    )
    assert saved.status_code == 200, saved.text
    handed = await app_client.post(
        f"/api/trainee/items/{ids[talked_id]}/handover",
        headers=headers,
        json={"job_id": job_id, "note": "Szuka od listopada"},
    )
    assert handed.status_code == 200, handed.text
    assert handed.json()["reopened_dismissed"] is True
    async with AsyncSessionLocal() as db:
        statuses = set(
            (
                await db.scalars(
                    select(JobProposal.status).where(
                        JobProposal.job_id == job_id,
                        JobProposal.candidate_id == talked_id,
                    )
                )
            ).all()
        )
    assert statuses == {"proposed"}


@needs_db
@pytest.mark.asyncio
async def test_list_rechecks_ranked_people_and_callbacks_against_the_pool() -> None:
    """M17: ranking z rana i oddzwonienia „później” przechodzą przez warunki
    puli — czarna lista i „nie kontaktować” po rankingu nie trafiają na listę."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.call import Call, CallDirection, CallStatus
    from app.models.candidate import CandidateStatus
    from app.models.trainee import TraineeCallItem, TraineeCallList

    skill = _skill()
    today = business_today()
    async with AsyncSessionLocal() as db:
        trainee, _ = await _world(db, skill=skill)
        ok = await _candidate(db, skill=skill)
        blacklisted_later = await _candidate(db, skill=skill)
        callback_ok = await _candidate(db, skill=skill)
        callback_dnc = await _candidate(db, skill=skill)
        # Oddzwonienia umówione wcześniej na dziś (pozycje z poprzedniej listy).
        old_list = TraineeCallList(
            user_id=trainee.id, list_date=today - timedelta(days=7), size=2
        )
        db.add(old_list)
        await db.flush()
        for pos, cand in enumerate((callback_ok, callback_dnc), start=1):
            db.add(
                TraineeCallItem(
                    list_id=old_list.id,
                    user_id=trainee.id,
                    candidate_id=cand.id,
                    list_date=old_list.list_date,
                    position=pos,
                    outcome="later",
                    closed_at=datetime.now(timezone.utc) - timedelta(days=7),
                    later_date=today,
                    reasons={"fits": 2},
                )
            )
        # Po umówieniu: rekruter usłyszał „nie kontaktujcie się”.
        db.add(
            Call(
                candidate_id=callback_dnc.id,
                direction=CallDirection.outbound,
                status=CallStatus.completed,
                contact_outcome="do_not_contact",
            )
        )
        # Po porannym rankingu: czarna lista.
        blacklisted_later.status = CandidateStatus.blacklisted
        await db.flush()
        await _list_with(db, trainee, [ok, blacklisted_later])
        await db.commit()
        rows = (
            await db.scalars(
                select(TraineeCallItem.candidate_id).where(
                    TraineeCallItem.user_id == trainee.id,
                    TraineeCallItem.list_date == today,
                )
            )
        ).all()

    assert ok.id in rows
    assert callback_ok.id in rows
    assert blacklisted_later.id not in rows
    assert callback_dnc.id not in rows


@needs_db
@pytest.mark.asyncio
async def test_empty_list_is_filled_on_a_later_attempt() -> None:
    """M18: pusta lista dnia (pula pusta rano) nie jest ostateczna."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_today
    from app.models.trainee import TraineeCallItem, TraineeCallList
    from app.services import trainee_call_list as lists

    skill = _skill()
    today = business_today()
    async with AsyncSessionLocal() as db:
        trainee, _ = await _world(db, skill=skill)
        cand = await _candidate(db, skill=skill)
        programs = [
            p
            for p in await lists.active_programs(db, today=today)
            if p.user_id == trainee.id
        ]
        first = await lists.generate_lists(db, programs, today=today, ranked=[])
        assert first == {trainee.id: 0}
        await db.commit()
        empty = await lists.list_for(db, trainee.id, today)
        assert empty is not None and empty.size == 0

        await _list_with(db, trainee, [cand])
        await db.commit()
        lists_today = (
            await db.scalars(
                select(TraineeCallList).where(
                    TraineeCallList.user_id == trainee.id,
                    TraineeCallList.list_date == today,
                )
            )
        ).all()
        assert [row.id for row in lists_today] == [empty.id]
        refreshed = await db.get(TraineeCallList, empty.id)
        await db.refresh(refreshed)
        assert refreshed.size == 1
        items = (
            await db.scalars(
                select(TraineeCallItem.candidate_id).where(
                    TraineeCallItem.list_id == empty.id
                )
            )
        ).all()
        assert items == [cand.id]


@needs_db
@pytest.mark.asyncio
async def test_preview_as_trainee_writes_nothing(app_client) -> None:
    """M21: admin w „podglądzie jako” nie zakłada programu ani listy."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.trainee import TraineeCallList, TraineeProgram

    async with AsyncSessionLocal() as db:
        trainee = await _user(db, "trainee")
        admin = await _user(db, "admin")
        await db.commit()
        trainee_id, admin_id = trainee.id, admin.id

    resp = await app_client.get(
        "/api/trainee/today",
        headers={
            **_headers(admin_id, "admin"),
            "X-Impersonate-User-Id": str(trainee_id),
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "no_program"
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(TraineeProgram).where(TraineeProgram.user_id == trainee_id)
            )
        ) is None
        assert (
            await db.scalar(
                select(TraineeCallList).where(TraineeCallList.user_id == trainee_id)
            )
        ) is None


@needs_db
@pytest.mark.asyncio
async def test_first_requests_race_creates_one_program(app_client) -> None:
    """M21: dwa równoległe pierwsze GET-y konta bez programu → oba 200."""
    import asyncio

    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models.trainee import TraineeProgram

    async with AsyncSessionLocal() as db:
        trainee = await _user(db, "trainee")
        await db.commit()
        trainee_id = trainee.id

    headers = _headers(trainee_id, "trainee")
    first, second = await asyncio.gather(
        app_client.get("/api/trainee/today", headers=headers),
        app_client.get("/api/trainee/today", headers=headers),
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(TraineeProgram)
            .where(TraineeProgram.user_id == trainee_id)
        )
    assert count == 1


@needs_db
@pytest.mark.asyncio
async def test_recruiter_corrects_call_facts_with_audit(app_client) -> None:
    """H4: pomyłkowe „Tylko etat” da się cofnąć; zostaje ślad starej wartości,
    a kandydat wraca do dopasowań."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.services.dealbreaker_filters import (
        DealbreakerInputs,
        apply_dealbreakers,
    )

    skill = _skill()
    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, "recruiter")
        viewer = await _user(db, "user")
        cand = await _candidate(
            db,
            skill=skill,
            b2b_willingness="employment_only",
            work_time_preference="part_time_only",
            accepts_below_min_rate=True,
        )
        await db.commit()
        recruiter_id, viewer_id, cand_id = recruiter.id, viewer.id, cand.id

    denied = await app_client.patch(
        f"/api/candidates/{cand_id}/call-facts",
        headers=_headers(viewer_id, "user"),
        json={"b2b_willingness": "b2b"},
    )
    assert denied.status_code == 403

    empty = await app_client.patch(
        f"/api/candidates/{cand_id}/call-facts",
        headers=_headers(recruiter_id, "recruiter"),
        json={},
    )
    assert empty.status_code == 422

    resp = await app_client.patch(
        f"/api/candidates/{cand_id}/call-facts",
        headers=_headers(recruiter_id, "recruiter"),
        json={"b2b_willingness": "b2b", "work_time_preference": None},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "candidate_id": cand_id,
        "b2b_willingness": "b2b",
        "work_time_preference": None,
        "accepts_below_min_rate": True,
        "accepts_more_office_days": None,
    }
    async with AsyncSessionLocal() as db:
        saved = await db.get(Candidate, cand_id)
        assert saved.b2b_willingness == "b2b"
        assert saved.work_time_preference is None
        assert saved.accepts_below_min_rate is True  # pominięte pole bez zmian
        audit = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == cand_id,
                Activity.action == "candidate_call_facts_corrected",
            )
        )
        assert audit is not None and audit.user_id == recruiter_id
        assert audit.details["changes"] == {
            "b2b_willingness": {"old": "employment_only", "new": "b2b"},
            "work_time_preference": {"old": "part_time_only", "new": None},
        }
        kept = apply_dealbreakers([saved], inputs=DealbreakerInputs()).kept
    assert [c.id for c in kept] == [cand_id]
