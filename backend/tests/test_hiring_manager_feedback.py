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
from datetime import datetime, timezone

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
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["candidate_id"] == world["candidate_id"]
    assert rows[0]["blocks_future_proposals"] is True


async def test_without_auth_it_is_closed(app_client) -> None:
    resp = await app_client.post(
        "/api/jobs/1/hiring-manager-feedback",
        json={"candidate_id": 1, "decision": "advance"},
    )
    assert resp.status_code in (401, 403), resp.text
