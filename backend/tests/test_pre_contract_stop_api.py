"""„Zatrzymaj do podpisu przedwstępnej” — API i ruch karty (0761, 23.11.2026).

Decyzje Artura: blokada przy osobie albo z ustawienia rekrutacji, od wybranego
etapu, obowiązuje też Delivery Leada; ustawia i zdejmuje DL klienta, Head of
Recruitment i admin; rekrutacja z ustawieniem zakłada prośby od
„Zweryfikowanego”. Każdy test zakłada własne dane (shard ma wspólną bazę).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.pre_contract import PreContractEvent, PreContractRequest
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


async def _user(db, role: UserRole) -> tuple[int, str, str]:
    suffix = uuid.uuid4().hex[:8]
    pwd = f"T3st_{suffix}!"
    user = User(
        email=f"pc-stop-{role.value}-{suffix}@example.com",
        password_hash=hash_password(pwd),
        name=f"Stop {role.value} {suffix}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user.id, user.email, pwd


async def _world(stage: PipelineStage = PipelineStage.screening) -> dict:
    async with AsyncSessionLocal() as db:
        recruiter = await _user(db, UserRole.recruiter)
        dl = await _user(db, UserRole.delivery_lead)
        other_dl = await _user(db, UserRole.delivery_lead)
        hor = await _user(db, UserRole.head_of_recruitment)
        client = Client(name=f"Stop {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title="Kierownik projektu",
            client_id=client.id,
            recruiter_id=recruiter[0],
            delivery_lead_id=dl[0],
            status=JobStatus.published,
        )
        candidate = Candidate(
            name="Ewa", lastname="Stopowa", email=f"es-{uuid.uuid4().hex[:8]}@x.com"
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=stage,
                moved_by=recruiter[0],
            )
        )
        await db.commit()
        return {
            "recruiter": recruiter,
            "dl": dl,
            "other_dl": other_dl,
            "hor": hor,
            "candidate_id": candidate.id,
            "job_id": job.id,
        }


async def _headers(client: AsyncClient, who: tuple[int, str, str]) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": who[1], "password": who[2]}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _requests(w: dict) -> list[PreContractRequest]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(PreContractRequest).where(
                        PreContractRequest.candidate_id == w["candidate_id"],
                        PreContractRequest.job_id == w["job_id"],
                    )
                )
            ).all()
        )


def _move(w: dict, stage: str) -> dict:
    return {"candidate_id": w["candidate_id"], "job_id": w["job_id"], "stage": stage}


async def test_person_stop_blocks_delivery_lead_move_to_cv_sent(app_client) -> None:
    w = await _world()
    dl = await _headers(app_client, w["dl"])
    made = await app_client.post(
        "/api/pre-contracts",
        headers=dl,
        json={
            "candidate_id": w["candidate_id"],
            "job_id": w["job_id"],
            "needed_before": "cv_sent",
            "blocks_move": True,
        },
    )
    assert made.status_code == 200, made.text
    assert made.json()["blocks_move"] is True

    blocked = await app_client.post(
        "/api/pipeline/move", headers=dl, json=_move(w, "cv_sent")
    )
    assert blocked.status_code == 409, blocked.text
    detail = blocked.json()["detail"]
    assert detail["code"] == "PRE_CONTRACT_NOT_SIGNED"
    assert detail["origin"] == "person"

    # Ruch na etap przed blokadą przechodzi.
    ok = await app_client.post(
        "/api/pipeline/move", headers=dl, json=_move(w, "interview")
    )
    assert ok.status_code == 200, ok.text


async def test_recruiter_cannot_set_or_lift_the_stop(app_client) -> None:
    w = await _world()
    rec = await _headers(app_client, w["recruiter"])
    denied = await app_client.post(
        "/api/pre-contracts",
        headers=rec,
        json={
            "candidate_id": w["candidate_id"],
            "job_id": w["job_id"],
            "blocks_move": True,
        },
    )
    assert denied.status_code == 403, denied.text
    assert await _requests(w) == []

    made = await app_client.post(
        "/api/pre-contracts",
        headers=rec,
        json={"candidate_id": w["candidate_id"], "job_id": w["job_id"]},
    )
    assert made.status_code == 200, made.text
    lift = await app_client.post(
        f"/api/pre-contracts/{made.json()['id']}/stop",
        headers=rec,
        json={"blocks_move": True},
    )
    assert lift.status_code == 403, lift.text


async def test_delivery_lead_of_another_client_cannot_set_the_rule(app_client) -> None:
    w = await _world()
    other = await _headers(app_client, w["other_dl"])
    resp = await app_client.put(
        f"/api/jobs/{w['job_id']}/pre-contract-rule",
        headers=other,
        json={"rule": {"needed_before": "cv_sent", "stop": True}},
    )
    assert resp.status_code == 403, resp.text


async def test_rule_from_head_of_recruitment_backfills_and_blocks(app_client) -> None:
    w = await _world(PipelineStage.interview)  # „Zweryfikowany”
    hor = await _headers(app_client, w["hor"])
    resp = await app_client.put(
        f"/api/jobs/{w['job_id']}/pre-contract-rule",
        headers=hor,
        json={"rule": {"needed_before": "cv_sent", "stop": True}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["requests_created"] == 1
    assert resp.json()["rule"]["stop"] is True
    [req] = await _requests(w)
    assert req.needed_before == "cv_sent" and req.blocks_move is None

    dl = await _headers(app_client, w["dl"])
    pair = await app_client.get(
        "/api/pre-contracts/pair",
        headers=dl,
        params={"candidate_id": w["candidate_id"], "job_id": w["job_id"]},
    )
    assert pair.status_code == 200, pair.text
    assert pair.json()["stop"]["origin"] == "job"
    assert pair.json()["can_set_stop"] is True

    blocked = await app_client.post(
        "/api/pipeline/move", headers=dl, json=_move(w, "cv_sent")
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"]["origin"] == "job"

    # Wyjątek DL-a dla tej osoby zwalnia kartę i zostaje w historii.
    exc = await app_client.post(
        f"/api/pre-contracts/{req.id}/stop", headers=dl, json={"blocks_move": False}
    )
    assert exc.status_code == 200, exc.text
    async with AsyncSessionLocal() as db:
        kinds = (
            await db.scalars(
                select(PreContractEvent.kind).where(
                    PreContractEvent.request_id == req.id
                )
            )
        ).all()
    assert "stop_exception" in kinds
    pair = await app_client.get(
        "/api/pre-contracts/pair",
        headers=dl,
        params={"candidate_id": w["candidate_id"], "job_id": w["job_id"]},
    )
    assert pair.json()["stop"] is None


async def test_move_into_verified_creates_the_rule_request(app_client) -> None:
    w = await _world(PipelineStage.screening)
    hor = await _headers(app_client, w["hor"])
    resp = await app_client.put(
        f"/api/jobs/{w['job_id']}/pre-contract-rule",
        headers=hor,
        json={"rule": {"needed_before": "client_interview", "stop": False}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["requests_created"] == 0  # osoba jeszcze w Screeningu
    moved = await app_client.post(
        "/api/pipeline/move", headers=hor, json=_move(w, "interview")
    )
    assert moved.status_code == 200, moved.text
    [req] = await _requests(w)
    assert req.needed_before == "client_interview"
    assert req.requested_by == w["hor"][0]
    assert req.assignee_id is not None


async def test_rule_can_be_removed(app_client) -> None:
    w = await _world()
    dl = await _headers(app_client, w["dl"])
    await app_client.put(
        f"/api/jobs/{w['job_id']}/pre-contract-rule",
        headers=dl,
        json={"rule": {"needed_before": "cv_sent", "stop": True}},
    )
    off = await app_client.put(
        f"/api/jobs/{w['job_id']}/pre-contract-rule", headers=dl, json={"rule": None}
    )
    assert off.status_code == 200, off.text
    assert off.json()["rule"] is None
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, w["job_id"])
        assert job.pre_contract_rule is None


async def test_recruiter_cannot_lift_a_stop_by_editing_or_recreating_the_request(
    app_client,
) -> None:
    w = await _world()
    dl = await _headers(app_client, w["dl"])
    rec = await _headers(app_client, w["recruiter"])
    made = await app_client.post(
        "/api/pre-contracts",
        headers=dl,
        json={
            "candidate_id": w["candidate_id"],
            "job_id": w["job_id"],
            "needed_before": "cv_sent",
            "blocks_move": True,
        },
    )
    rid = made.json()["id"]
    # Przegląd 23.11: „Do daty…” zdejmowałoby stop — zmiana etapu tylko dla DL/HoR.
    patch = await app_client.patch(
        f"/api/pre-contracts/{rid}",
        headers=rec,
        json={"needed_before": "date", "needed_by": "2026-12-31"},
    )
    assert patch.status_code == 403, patch.text
    # Anuluj + poproś od nowa: nowa prośba przejmuje stop.
    cancel = await app_client.post(
        f"/api/pre-contracts/{rid}/cancel", headers=rec, json={"reason": "Pomyłka"}
    )
    assert cancel.status_code == 200, cancel.text
    blocked = await app_client.post(
        "/api/pipeline/move", headers=dl, json=_move(w, "cv_sent")
    )
    assert blocked.status_code == 409, blocked.text
    again = await app_client.post(
        "/api/pre-contracts",
        headers=rec,
        json={
            "candidate_id": w["candidate_id"],
            "job_id": w["job_id"],
            "needed_before": "b2b_contract",
        },
    )
    assert again.status_code == 200, again.text
    assert again.json()["blocks_move"] is True
    blocked = await app_client.post(
        "/api/pipeline/move", headers=dl, json=_move(w, "cv_sent")
    )
    assert blocked.status_code == 409, blocked.text


async def test_changing_the_rule_stage_moves_inherited_requests(app_client) -> None:
    w = await _world(PipelineStage.interview)
    hor = await _headers(app_client, w["hor"])
    await app_client.put(
        f"/api/jobs/{w['job_id']}/pre-contract-rule",
        headers=hor,
        json={"rule": {"needed_before": "cv_sent", "stop": True}},
    )
    await app_client.put(
        f"/api/jobs/{w['job_id']}/pre-contract-rule",
        headers=hor,
        json={"rule": {"needed_before": "b2b_contract", "stop": True}},
    )
    [req] = await _requests(w)
    assert req.needed_before == "b2b_contract"


async def test_automatic_advance_stops_before_the_contract(app_client) -> None:
    from app.services.pipeline_auto_move import auto_advance
    from app.services.pre_contract_stop import SKIP_REASON

    w = await _world(PipelineStage.cv_sent)
    hor = await _headers(app_client, w["hor"])
    resp = await app_client.put(
        f"/api/jobs/{w['job_id']}/pre-contract-rule",
        headers=hor,
        json={"rule": {"needed_before": "client_interview", "stop": True}},
    )
    assert resp.status_code == 200, resp.text
    reasons: list[str] = []
    async with AsyncSessionLocal() as db:
        moved = await auto_advance(
            db,
            candidate_id=w["candidate_id"],
            job_id=w["job_id"],
            target=PipelineStage.client_interview,
            actor_user_id=w["dl"][0],
            source="interview_slots",
            note="test",
            skip_reasons=reasons,
        )
        await db.rollback()
    assert moved is None
    assert reasons == [SKIP_REASON]


async def test_rule_is_saved_when_the_job_is_created(
    app_client, app_auth_headers, monkeypatch
) -> None:
    from app.services import canonical_fit, embedding_service
    from tests._job_factory import complete_job_payload

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(canonical_fit, "score_candidates", _empty)

    async with AsyncSessionLocal() as db:
        client = Client(name=f"StopNew-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.commit()
        client_id = client.id
    payload = await complete_job_payload(client_id)
    payload["pre_contract_rule"] = {"needed_before": "client_interview", "stop": True}
    resp = await app_client.post("/api/jobs", json=payload, headers=app_auth_headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["pre_contract_rule"]["needed_before"] == "client_interview"
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, resp.json()["id"])
        assert job.pre_contract_rule["stop"] is True
        assert job.pre_contract_rule["set_by"] is not None
