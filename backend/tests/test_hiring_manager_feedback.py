"""Werdykt hiring managera ma własne miejsce — i nie udaje weta.

Krok 07 „Rozmowy i decyzja" (program „flow w języku C2"). Do 09.2026 to, co
manager powiedział po rozmowie, dawało się zapisać wyłącznie jako skutek
uboczny odrzucenia kandydata. `POST /api/jobs/{id}/hiring-manager-feedback`
zapisuje werdykt osobno.

Te testy pilnują przede wszystkim GRANICY, którą najłatwiej przekroczyć przy
kolejnej zmianie: endpoint NIE tworzy weta. Weto jest WYPROWADZANE przez
`services/hiring_manager_verdicts` z etapu `rejected` + powodu oznaczonego
`disqualifies_person`. Gdyby zapis werdyktu zaczął sam z siebie raportować
`veto_recorded=True`, UI pokazywałoby chip „Weto HM" dla kandydata, którego
`POST /api/pipeline/move` przepuszcza bez mrugnięcia — a to jest dokładnie ta
klasa rozjazdu, przez którą bramki przestają być bramkami.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import app.models  # noqa: F401  (zarejestruj wszystkie mappery)
from app.models.skill import Skill  # noqa: F401
from sqlalchemy import select

NOW = datetime(2036, 4, 7, 9, 0, tzinfo=timezone.utc)


async def _seed(*, with_manager: bool = True) -> dict:
    """Klient + (opcjonalnie) hiring manager + rekrutacja + kandydat w procesie.

    Powody odrzucenia zakładamy na WŁASNYM szablonie tej rekrutacji, bo
    endpoint sprawdza spójność `reason.template_id` z `job.pipeline_template_id`
    — testowanie na powodach szablonu domyślnego omijałoby tę kontrolę.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.contact import Contact
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineTemplate,
        RejectionReason,
        TerminalType,
    )
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"HMFeedbackClient-{tag}")
        template = PipelineTemplate(name=f"HMFeedbackTemplate-{tag}")
        db.add_all([client, template])
        await db.commit()
        await db.refresh(client)
        await db.refresh(template)

        manager_id = None
        if with_manager:
            manager = Contact(
                name=f"Anna Manager-{tag}",
                email=f"hm-{tag}@example.com",
                client_id=client.id,
            )
            db.add(manager)
            await db.commit()
            await db.refresh(manager)
            manager_id = manager.id

        person_verdict = RejectionReason(
            template_id=template.id,
            name=f"Nie spełnia wymagań technicznych {tag}",
            category=TerminalType.rejected,
            disqualifies_person=True,
        )
        situation_reason = RejectionReason(
            template_id=template.id,
            name=f"Za wysokie oczekiwania finansowe {tag}",
            category=TerminalType.rejected,
            disqualifies_person=False,
        )
        withdrawn_reason = RejectionReason(
            template_id=template.id,
            name=f"Kandydat się wycofał {tag}",
            category=TerminalType.withdrawn,
            disqualifies_person=False,
        )
        job = Job(
            title=f"HMFeedbackJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            pipeline_template_id=template.id,
            hiring_manager_contact_id=manager_id,
        )
        candidate = Candidate(
            name="Grzegorz",
            lastname=f"Werdykt-{tag}",
            email=f"cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([person_verdict, situation_reason, withdrawn_reason, job, candidate])
        await db.commit()
        for row in (person_verdict, situation_reason, withdrawn_reason, job, candidate):
            await db.refresh(row)

        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.client_interview,
                moved_at=NOW,
            )
        )
        await db.commit()

        return {
            "job_id": job.id,
            "candidate_id": candidate.id,
            "client_id": client.id,
            "template_id": template.id,
            "manager_id": manager_id,
            "person_verdict_reason_id": person_verdict.id,
            "situation_reason_id": situation_reason.id,
            "withdrawn_reason_id": withdrawn_reason.id,
        }


async def test_records_the_verdict_and_names_the_reason(
    app_client, app_auth_headers
) -> None:
    world = await _seed()

    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "decision": "reject",
            "rejection_reason_id": world["person_verdict_reason_id"],
            "note": "Nie przekonał przy pytaniach o Kafkę pod obciążeniem.",
            "technical_fit": 2,
            "overall_fit": 2,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["decision"] == "reject"
    assert body["rejection_reason_id"] == world["person_verdict_reason_id"]
    assert "Nie spełnia wymagań technicznych" in body["rejection_reason_name"]
    assert body["note"].startswith("Nie przekonał")
    assert body["technical_fit"] == 2
    assert body["hiring_manager_contact_id"] == world["manager_id"]


async def test_a_disqualifying_reason_does_not_by_itself_record_a_veto(
    app_client, app_auth_headers
) -> None:
    """Najważniejszy test w tym pliku.

    Powód JEST oznaczony jako werdykt o osobie, manager JEST przypisany,
    kandydat BYŁ na rozmowie u klienta — a mimo to weta nie ma, bo nikt go
    jeszcze nie odrzucił. `blocks_future_proposals` mówi o POWODZIE,
    `veto_recorded` o STANIE FAKTYCZNYM. Zlanie tych dwóch pól w jedno
    zamieniłoby chip „Weto HM" w obietnicę, której backend nie dotrzyma.
    """
    world = await _seed()

    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "decision": "reject",
            "rejection_reason_id": world["person_verdict_reason_id"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["blocks_future_proposals"] is True
    assert body["veto_recorded"] is False
    assert any("odrzucony" in blocker for blocker in body["veto_blockers"]), body[
        "veto_blockers"
    ]


async def test_a_situational_reason_reports_that_it_will_not_block(
    app_client, app_auth_headers
) -> None:
    world = await _seed()

    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "decision": "reject",
            "rejection_reason_id": world["situation_reason_id"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["blocks_future_proposals"] is False
    assert any("nie osobę" in b or "sytuację" in b for b in body["veto_blockers"]), (
        body["veto_blockers"]
    )


async def test_a_job_without_a_hiring_manager_says_so(
    app_client, app_auth_headers
) -> None:
    """Bez managera weto nie ma komu przypisać kandydata — i trzeba to napisać.

    Milczenie tutaj jest gorsze niż odmowa: rekruter zapisuje werdykt
    „blokuje ponowne propozycje" i nie dowiaduje się, że nie zablokuje niczego.
    """
    world = await _seed(with_manager=False)

    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "decision": "reject",
            "rejection_reason_id": world["person_verdict_reason_id"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["hiring_manager_contact_id"] is None
    assert any("hiring managera" in b for b in body["veto_blockers"]), body[
        "veto_blockers"
    ]


async def test_second_call_updates_the_same_row_instead_of_stacking(
    app_client, app_auth_headers
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.interview_feedback import FeedbackSource, InterviewFeedback

    world = await _seed()
    first = await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={"candidate_id": world["candidate_id"], "decision": "on_hold"},
    )
    assert first.status_code == 201, first.text

    second = await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "decision": "advance",
            "note": "Klient chce drugą rozmowę.",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["decision"] == "advance"

    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(InterviewFeedback).where(
                        InterviewFeedback.job_id == world["job_id"],
                        InterviewFeedback.feedback_source == FeedbackSource.client_side,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1, "powtórny werdykt ma nadpisywać, nie hodować stosu"


async def test_a_withdrawal_reason_is_rejected(app_client, app_auth_headers) -> None:
    """Powód z kategorii „wycofany" opisuje decyzję KANDYDATA, nie klienta."""
    world = await _seed()

    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "decision": "reject",
            "rejection_reason_id": world["withdrawn_reason_id"],
        },
    )
    assert resp.status_code == 422, resp.text


async def test_a_reason_from_another_template_is_rejected(
    app_client, app_auth_headers
) -> None:
    """Silnik weta czyta powód po FK — obcy powód czytałby się jak swój."""
    other = await _seed()
    world = await _seed()

    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "decision": "reject",
            "rejection_reason_id": other["person_verdict_reason_id"],
        },
    )
    assert resp.status_code == 422, resp.text


async def test_a_candidate_outside_this_pipeline_is_not_found(
    app_client, app_auth_headers
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    world = await _seed()
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        stranger = Candidate(
            name="Obcy",
            lastname=f"Kandydat-{tag}",
            email=f"stranger-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add(stranger)
        await db.commit()
        await db.refresh(stranger)
        stranger_id = stranger.id

    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={"candidate_id": stranger_id, "decision": "advance"},
    )
    assert resp.status_code == 404, resp.text


async def test_listing_returns_one_verdict_per_candidate(
    app_client, app_auth_headers
) -> None:
    world = await _seed()
    await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "decision": "reject",
            "rejection_reason_id": world["person_verdict_reason_id"],
        },
    )

    resp = await app_client.get(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()["items"]
    assert len(rows) == 1
    assert rows[0]["candidate_id"] == world["candidate_id"]
    assert rows[0]["blocks_future_proposals"] is True
    # Admin przejdzie POST — formularz ma być edytowalny.
    assert resp.json()["can_record"] is True


async def test_without_auth_it_is_closed(app_client) -> None:
    resp = await app_client.post(
        "/api/jobs/1/hiring-manager-feedback",
        json={"candidate_id": 1, "decision": "advance"},
    )
    assert resp.status_code in (401, 403), resp.text


async def _add_rejection(
    job_id: int, candidate_id: int, reason_id: int, moved_at
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage.rejected,
                rejection_reason_id=reason_id,
                moved_at=moved_at,
            )
        )
        await db.commit()


async def test_veto_requires_the_meeting_to_precede_the_rejection(
    app_client, app_auth_headers
) -> None:
    """`veto_recorded` liczy się DOKŁADNIE jak silnik (`load_manager_rejections`):
    spotkanie z managerem musi POPRZEDZAĆ odrzuczenie (`met.moved_at <=
    rejected.moved_at`). Agregat „był kiedyś client_interview i był kiedyś
    rejected" pasowałby też do `rejected → wznowienie → client_interview` —
    UI mówiłoby „weto stoi", a `/pipeline/move` przepuszczałby ruch.
    """
    world = await _seed()  # client_interview @ NOW

    # Odrzucenie PRZED spotkaniem (dzień wcześniej) → historia odwrotna → brak weta.
    await _add_rejection(
        world["job_id"],
        world["candidate_id"],
        world["person_verdict_reason_id"],
        NOW - timedelta(days=1),
    )
    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "decision": "reject",
            "rejection_reason_id": world["person_verdict_reason_id"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["veto_recorded"] is False
    assert any("PRZED" in blocker for blocker in body["veto_blockers"]), body[
        "veto_blockers"
    ]

    # Odrzucenie PO spotkaniu (dzień później) → weto stoi.
    await _add_rejection(
        world["job_id"],
        world["candidate_id"],
        world["person_verdict_reason_id"],
        NOW + timedelta(days=1),
    )
    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/hiring-manager-feedback",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "decision": "reject",
            "rejection_reason_id": world["person_verdict_reason_id"],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["veto_recorded"] is True, body["veto_blockers"]
    assert body["veto_blockers"] == []


# ── Kto może czytać i kto może NADPISAĆ werdykt (09.2026) ────────────────────


async def _role_headers(role, *, member_of_job: int | None = None) -> tuple[dict, int]:
    """Użytkownik danej roli z tokenem; opcjonalnie członek zespołu rekrutacji."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token, hash_password
    from app.models.job_collaborator import JobCollaborator
    from app.models.user import User

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"hm-{role.value}-{tag}@example.com",
            password_hash=hash_password("x"),
            name=f"HM {role.value} {tag}",
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.flush()
        if member_of_job is not None:
            db.add(JobCollaborator(job_id=member_of_job, user_id=user.id))
        await db.commit()
        await db.refresh(user)
        token = create_access_token(user.id, role.value, roles=[role.value])
        return {"Authorization": f"Bearer {token}"}, user.id


def _url(world: dict) -> str:
    return f"/api/jobs/{world['job_id']}/hiring-manager-feedback"


async def test_finance_reads_and_records_verdicts_without_team_membership(
    app_client, app_auth_headers
) -> None:
    """Finance czyta werdykty rekrutacji spoza zespołu — i od 23.09.2026 może
    też zapisać swój (decyzja Artura: rekrutację obsługuje każdy, bez
    przypisania). Cudzego werdyktu nadal nie nadpisuje.
    """
    from app.models.user import UserRole

    world = await _seed()
    await app_client.post(
        _url(world),
        headers=app_auth_headers,
        json={"candidate_id": world["candidate_id"], "decision": "advance"},
    )
    finance_headers, _ = await _role_headers(UserRole.finance)

    resp = await app_client.get(_url(world), headers=finance_headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["items"]
    assert len(rows) == 1
    # Finance nie jest autorem ani DL/adminem — podgląd, bez nadpisywania.
    assert rows[0]["can_edit"] is False
    # Bramka zespołu nie odcina już zapisu, więc formularz jest dostępny.
    assert resp.json()["can_record"] is True


async def test_a_colleague_cannot_silently_overwrite_someone_elses_verdict(
    app_client,
) -> None:
    """Upsert po parze (kandydat, rekrutacja) podmieniał autora i treść.

    Drugi rekruter z tego samego zespołu kasował werdykt kolegi jednym
    „Zapisz". Teraz nadpisuje wyłącznie autor, Delivery Lead albo admin —
    ta sama reguła co `PATCH /api/interview-feedback`.
    """
    from app.models.user import UserRole

    world = await _seed()
    author_headers, author_id = await _role_headers(
        UserRole.recruiter, member_of_job=world["job_id"]
    )
    colleague_headers, _ = await _role_headers(
        UserRole.recruiter, member_of_job=world["job_id"]
    )

    first = await app_client.post(
        _url(world),
        headers=author_headers,
        json={
            "candidate_id": world["candidate_id"],
            "decision": "reject",
            "rejection_reason_id": world["person_verdict_reason_id"],
            "note": "Manager odrzucił po rozmowie technicznej.",
        },
    )
    assert first.status_code == 201, first.text

    second = await app_client.post(
        _url(world),
        headers=colleague_headers,
        json={"candidate_id": world["candidate_id"], "decision": "advance"},
    )
    assert second.status_code == 403, second.text
    assert "zmienić go może autor" in second.json()["detail"]

    as_author = (await app_client.get(_url(world), headers=author_headers)).json()
    assert as_author["items"][0]["decision"] == "reject"
    assert as_author["items"][0]["author_id"] == author_id
    assert as_author["items"][0]["can_edit"] is True

    as_colleague = (await app_client.get(_url(world), headers=colleague_headers)).json()
    # Kolega z zespołu MOŻE zapisywać werdykty — tylko nie nadpisać cudzego.
    assert as_colleague["can_record"] is True
    assert as_colleague["items"][0]["can_edit"] is False
    assert as_colleague["items"][0]["author_name"].startswith("HM recruiter")


async def test_author_and_delivery_lead_may_update_the_verdict(app_client) -> None:
    from app.models.user import UserRole

    world = await _seed()
    author_headers, _ = await _role_headers(
        UserRole.recruiter, member_of_job=world["job_id"]
    )
    dl_headers, dl_id = await _role_headers(UserRole.delivery_lead)

    created = await app_client.post(
        _url(world),
        headers=author_headers,
        json={"candidate_id": world["candidate_id"], "decision": "on_hold"},
    )
    assert created.status_code == 201, created.text

    by_author = await app_client.post(
        _url(world),
        headers=author_headers,
        json={"candidate_id": world["candidate_id"], "decision": "advance"},
    )
    assert by_author.status_code == 201, by_author.text
    assert by_author.json()["id"] == created.json()["id"]

    by_dl = await app_client.post(
        _url(world),
        headers=dl_headers,
        json={"candidate_id": world["candidate_id"], "decision": "reject"},
    )
    assert by_dl.status_code == 201, by_dl.text
    assert by_dl.json()["id"] == created.json()["id"]
    assert by_dl.json()["author_id"] == dl_id


async def test_head_of_recruitment_reads_and_records(app_client) -> None:
    """Parytet HoR z rekruterem 2026-09-17: HoR jest w `RecruiterPlus`
    i omija członkostwo w zespole (rola nadzoru), więc zapis przechodzi.

    `can_edit` na CUDZYM werdykcie: `_can_edit` z modułu feedbacku przepuszcza
    HoR (nadzór może poprawić werdykt zespołu), a zapis już nie odmawia —
    więc przycisk nie obiecuje 403. Świadomie `True`.
    """
    from app.models.user import UserRole

    world = await _seed()
    author_headers, _ = await _role_headers(
        UserRole.recruiter, member_of_job=world["job_id"]
    )
    await app_client.post(
        _url(world),
        headers=author_headers,
        json={"candidate_id": world["candidate_id"], "decision": "advance"},
    )
    hor_headers, _ = await _role_headers(UserRole.head_of_recruitment)

    listed = await app_client.get(_url(world), headers=hor_headers)
    assert listed.status_code == 200, listed.text
    # parytet HoR z rekruterem 2026-09-17
    assert listed.json()["items"][0]["can_edit"] is True
    assert listed.json()["can_record"] is True

    write = await app_client.post(
        _url(world),
        headers=hor_headers,
        json={"candidate_id": world["candidate_id"], "decision": "reject"},
    )
    assert write.status_code == 201, write.text


# ── Werdykt zapisany z okna wydarzenia w kalendarzu (audyt 17.09.2026) ───────


async def _seed_event_feedback(world: dict, *, author_id: int | None = None) -> dict:
    """Rozmowa w kalendarzu + feedback klienta zapisany pod nią (`needs_attention`)."""
    from app.core.database import AsyncSessionLocal
    from app.models.calendar_event import CalendarEvent, EventStatus, EventType
    from app.models.interview_feedback import (
        FeedbackSource,
        InterviewDecision,
        InterviewFeedback,
    )

    async with AsyncSessionLocal() as db:
        event = CalendarEvent(
            title="Rozmowa u klienta",
            event_type=EventType.interview,
            start_time=NOW - timedelta(days=2),
            end_time=NOW - timedelta(days=2) + timedelta(hours=1),
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            status=EventStatus.completed,
            needs_attention=True,
            created_by=author_id,
        )
        db.add(event)
        await db.flush()
        feedback = InterviewFeedback(
            calendar_event_id=event.id,
            candidate_id=world["candidate_id"],
            job_id=world["job_id"],
            author_id=author_id,
            feedback_source=FeedbackSource.client_side,
            decision=InterviewDecision.on_hold,
            feedback_summary="Klient chce się zastanowić.",
        )
        db.add(feedback)
        await db.commit()
        return {"event_id": event.id, "feedback_id": feedback.id}


async def test_listing_includes_the_verdict_saved_from_a_calendar_event(
    app_client, app_auth_headers
) -> None:
    """Karta rekrutacji mówiła „do uzupełnienia" nad werdyktem zapisanym
    w kalendarzu, bo lista czytała tylko wiersze bez spotkania."""
    world = await _seed()
    seeded = await _seed_event_feedback(world)

    resp = await app_client.get(_url(world), headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()["items"]
    assert len(rows) == 1
    assert rows[0]["id"] == seeded["feedback_id"]
    assert rows[0]["calendar_event_id"] == seeded["event_id"]
    assert rows[0]["event_title"] == "Rozmowa u klienta"
    assert rows[0]["event_start_time"] is not None
    assert rows[0]["decision"] == "on_hold"


async def test_recording_from_the_card_keeps_the_calendar_verdict_and_clears_attention(
    app_client, app_auth_headers
) -> None:
    """Werdykt z karty to OSOBNY wiersz bez wydarzenia (przegląd 17.09.2026).

    Wiersz przypięty do rozmowy opisuje tę rozmowę — nadpisanie gubiło notatkę
    rundy 1, a FK z ON DELETE CASCADE kasowało werdykt z karty razem ze
    spotkaniem. Lista pokazuje ostatnio zmieniony wiersz, więc po zapisie karta
    widzi swój werdykt; flaga „brak feedbacku" na rozmowie gaśnie.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.calendar_event import CalendarEvent
    from app.models.interview_feedback import FeedbackSource, InterviewFeedback

    world = await _seed()
    seeded = await _seed_event_feedback(world)

    resp = await app_client.post(
        _url(world),
        headers=app_auth_headers,
        json={"candidate_id": world["candidate_id"], "decision": "advance"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] != seeded["feedback_id"]
    assert resp.json()["calendar_event_id"] is None

    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(InterviewFeedback).where(
                        InterviewFeedback.job_id == world["job_id"],
                        InterviewFeedback.feedback_source == FeedbackSource.client_side,
                    )
                )
            )
            .scalars()
            .all()
        )
        event = await db.get(CalendarEvent, seeded["event_id"])
    by_id = {row.id: row for row in rows}
    assert len(rows) == 2
    assert by_id[seeded["feedback_id"]].decision.value == "on_hold"
    assert (
        by_id[seeded["feedback_id"]].feedback_summary == "Klient chce się zastanowić."
    )
    assert event is not None and event.needs_attention is False

    listed = await app_client.get(_url(world), headers=app_auth_headers)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()["items"]] == [resp.json()["id"]]

    # Drugi zapis z karty edytuje TEN SAM wiersz bez wydarzenia.
    again = await app_client.post(
        _url(world),
        headers=app_auth_headers,
        json={"candidate_id": world["candidate_id"], "decision": "reject"},
    )
    assert again.status_code == 201, again.text
    assert again.json()["id"] == resp.json()["id"]


# ── `can_record`: formularz tylko dla tych, których POST przepuści (09.2026) ──


async def test_can_record_matches_the_post_for_every_persona(
    app_client, app_auth_headers
) -> None:
    """`can_record` z odczytu = wynik PRAWDZIWEGO zapisu, persona po personie.

    Do 09.2026 formularz decydował po capability roli, a zapis dodatkowo po
    członkostwie w zespole — Finance (tier RecruiterPlus) na cudzej rekrutacji
    widziało aktywne „Zapisz feedback" kończące się 403. Każda persona dostaje
    własną rekrutację, żeby reguła nadpisywania CUDZEGO werdyktu (`can_edit`)
    nie mieszała się z prawem do zapisu.
    """
    from app.models.user import UserRole

    # Od 23.09.2026 bramka zespołu przepuszcza każdą rolę wewnętrzną, więc
    # także osoby spoza zespołu (rekruter, Finance) zapisują werdykt.
    cases = [
        ("admin", None, True),
        ("recruiter-member", UserRole.recruiter, True),
        ("recruiter-outsider", UserRole.recruiter, True),
        ("finance-member", UserRole.finance, True),
        ("finance-outsider", UserRole.finance, True),
        # Obejście członkostwa dla Delivery Leada — to samo co w POST.
        ("delivery-lead-outsider", UserRole.delivery_lead, True),
        # Parytet HoR z rekruterem 2026-09-17 (rola nadzoru omija członkostwo).
        ("head-of-recruitment", UserRole.head_of_recruitment, True),
    ]
    for label, role, expected in cases:
        world = await _seed()
        if role is None:
            headers = app_auth_headers
        else:
            headers, _ = await _role_headers(
                role,
                member_of_job=world["job_id"] if label.endswith("-member") else None,
            )

        listed = await app_client.get(_url(world), headers=headers)
        assert listed.status_code == 200, (label, listed.text)
        can_record = listed.json()["can_record"]

        write = await app_client.post(
            _url(world),
            headers=headers,
            json={"candidate_id": world["candidate_id"], "decision": "on_hold"},
        )
        assert write.status_code in (201, 403), (label, write.text)
        assert can_record is (write.status_code == 201), (label, can_record, write.text)
        assert can_record is expected, label


async def test_impersonated_view_cannot_record(app_client, app_auth_headers) -> None:
    """Podgląd „jako użytkownik" jest tylko do odczytu — POST dostałby 403."""
    from app.models.user import UserRole

    world = await _seed()
    _, member_id = await _role_headers(
        UserRole.recruiter, member_of_job=world["job_id"]
    )

    listed = await app_client.get(
        _url(world),
        headers={**app_auth_headers, "X-Impersonate-User-Id": str(member_id)},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["can_record"] is False
