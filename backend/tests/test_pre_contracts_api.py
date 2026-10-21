"""Umowa przedwstępna przy osobie w rekrutacji — API (0505, 21.10.2026).

Droga z makiet: Delivery Lead prosi → rekruter prowadzący wystawia (Generator),
wysyła, wgrywa umowę podpisaną przez kandydata (dowolna forma podpisu) i przez
firmę. Proszący i obserwujący dostają dzwonek przy każdym kroku, autor kroku
nie. Każdy test zakłada własne dane (shard ma wspólną bazę).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.services.candidate_followups import add_business_days
from app.core.security import hash_password
from app.models.b2b_contract_document import B2BContractDocument
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.pre_contract import PreContractRequest
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio

PDF = b"%PDF-1.4\n% test\n"


async def _user(db, role: UserRole) -> tuple[User, str]:
    suffix = uuid.uuid4().hex[:8]
    pwd = f"T3st_{suffix}!"
    user = User(
        email=f"pre-contract-{role.value}-{suffix}@example.com",
        password_hash=hash_password(pwd),
        name=f"Pc {role.value} {suffix}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user, pwd


async def _pair() -> dict:
    async with AsyncSessionLocal() as db:
        recruiter, rpwd = await _user(db, UserRole.recruiter)
        dl, dpwd = await _user(db, UserRole.delivery_lead)
        client = Client(name=f"PreContract {uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title="Analityk systemowy",
            client_id=client.id,
            recruiter_id=recruiter.id,
            delivery_lead_id=dl.id,
            status=JobStatus.published,
        )
        candidate = Candidate(
            name="Anna", lastname="Testowa", email=f"at-{uuid.uuid4().hex[:8]}@x.com"
        )
        db.add_all([job, candidate])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.screening,
                moved_by=recruiter.id,
            )
        )
        await db.commit()
        return {
            "recruiter": (recruiter.id, recruiter.email, rpwd),
            "dl": (dl.id, dl.email, dpwd),
            "candidate_id": candidate.id,
            "job_id": job.id,
            "client_id": client.id,
        }


async def _headers(client: AsyncClient, who: tuple[int, str, str]) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": who[1], "password": who[2]}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _bells(user_id: int) -> list[Notification]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(Notification)
                    .where(
                        Notification.user_id == user_id,
                        Notification.notification_type == NotificationType.pre_contract,
                    )
                    .order_by(Notification.id)
                )
            ).all()
        )


async def _document(pair: dict, *, valid_until: date) -> int:
    async with AsyncSessionLocal() as db:
        doc = B2BContractDocument(
            document_type="preliminary_cez",
            language="pl",
            candidate_id=pair["candidate_id"],
            job_id=pair["job_id"],
            client_id=pair["client_id"],
            document_date=date(2026, 10, 21),
            render_payload={"values": {"valid_until": valid_until.isoformat()}},
            template_key="preliminary_cez_pl",
            created_by=pair["recruiter"][0],
        )
        db.add(doc)
        await db.commit()
        return doc.id


async def test_dl_request_goes_to_pair_recruiter_and_tracks_every_step(
    app_client: AsyncClient,
) -> None:
    pair = await _pair()
    dl_h = await _headers(app_client, pair["dl"])
    rec_h = await _headers(app_client, pair["recruiter"])

    resp = await app_client.post(
        "/api/pre-contracts",
        headers=dl_h,
        json={
            "candidate_id": pair["candidate_id"],
            "job_id": pair["job_id"],
            "needed_before": "cv_sent",
            "reason": "Klient zaprasza tylko dwie osoby na test.",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    request_id = body["id"]
    assert body["state"] == "requested"
    assert body["assignee"]["id"] == pair["recruiter"][0]
    assert body["badge"]["tone"] == "missing"
    assert {w["id"] for w in body["watchers"]} == {pair["dl"][0], pair["recruiter"][0]}
    [bell] = await _bells(pair["recruiter"][0])
    assert "prosi o umowę przedwstępną przed wysłaniem CV" in bell.message
    assert bell.link == f"/jobs/{pair['job_id']}?candidate={pair['candidate_id']}"
    assert await _bells(pair["dl"][0]) == []  # autor prośby nie dostaje dzwonka

    valid_until = business_today() + timedelta(days=60)
    doc_id = await _document(pair, valid_until=valid_until)
    listed = await app_client.get(
        "/api/pre-contracts/pair",
        headers=rec_h,
        params={"candidate_id": pair["candidate_id"], "job_id": pair["job_id"]},
    )
    assert [d["id"] for d in listed.json()["documents"]] == [doc_id]
    assert listed.json()["current"]["id"] == request_id
    resp = await app_client.post(
        f"/api/pre-contracts/{request_id}/document",
        headers=rec_h,
        json={"document_id": doc_id},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "issued"
    assert resp.json()["valid_until"] == valid_until.isoformat()

    resp = await app_client.post(
        f"/api/pre-contracts/{request_id}/sent", headers=rec_h, json={}
    )
    assert resp.json()["state"] == "sent"

    resp = await app_client.post(
        f"/api/pre-contracts/{request_id}/candidate-signed",
        headers=rec_h,
        data={"signature_form": "trusted_profile"},
        files={"file": ("umowa.pdf", PDF, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidate_signature_form_label"] == "profil zaufany"

    resp = await app_client.post(
        f"/api/pre-contracts/{request_id}/company-signed",
        headers=rec_h,
        files={"file": ("umowa-obie.pdf", PDF, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "signed"
    assert body["badge"]["tone"] == "ok"
    assert [e["kind"] for e in body["events"]] == [
        "requested",
        "issued",
        "sent",
        "candidate_signed",
        "company_signed",
    ]

    # Każdy krok rekrutera = dzwonek u Delivery Leada (4 kroki, ten sam dzień).
    assert len(await _bells(pair["dl"][0])) == 4

    # Stan dokumentu w Generatorze zostaje — tam podpis ma własne bramki.
    async with AsyncSessionLocal() as db:
        doc = await db.get(B2BContractDocument, doc_id)
        assert doc.signature_status == "unsigned"

    # Podpisanych plików nie podmieniamy — to dowód do decyzji o karze.
    locked = await app_client.post(
        f"/api/pre-contracts/{request_id}/candidate-signed",
        headers=rec_h,
        data={"signature_form": "other"},
        files={"file": ("inna.pdf", PDF, "application/pdf")},
    )
    assert locked.status_code == 409

    resp = await app_client.get(
        f"/api/pre-contracts/{request_id}/files/candidate", headers=dl_h
    )
    assert resp.status_code == 200 and resp.content == PDF


async def test_second_request_joins_watchers_instead_of_new_contract(
    app_client: AsyncClient,
) -> None:
    pair = await _pair()
    dl_h = await _headers(app_client, pair["dl"])
    rec_h = await _headers(app_client, pair["recruiter"])
    first = await app_client.post(
        "/api/pre-contracts",
        headers=rec_h,
        json={"candidate_id": pair["candidate_id"], "job_id": pair["job_id"]},
    )
    second = await app_client.post(
        "/api/pre-contracts",
        headers=dl_h,
        json={"candidate_id": pair["candidate_id"], "job_id": pair["job_id"]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["watching"] is True
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(PreContractRequest).where(
                    PreContractRequest.candidate_id == pair["candidate_id"]
                )
            )
        ).all()
    assert len(rows) == 1


async def test_withdraw_only_before_sending_and_only_by_requester(
    app_client: AsyncClient,
) -> None:
    pair = await _pair()
    dl_h = await _headers(app_client, pair["dl"])
    rec_h = await _headers(app_client, pair["recruiter"])
    created = await app_client.post(
        "/api/pre-contracts",
        headers=dl_h,
        json={"candidate_id": pair["candidate_id"], "job_id": pair["job_id"]},
    )
    request_id = created.json()["id"]
    denied = await app_client.post(
        f"/api/pre-contracts/{request_id}/withdraw", headers=rec_h
    )
    assert denied.status_code == 403
    ok = await app_client.post(
        f"/api/pre-contracts/{request_id}/withdraw", headers=dl_h
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["state"] == "withdrawn" and ok.json()["is_open"] is False


async def test_candidate_withdrawal_needs_signed_contract_and_waits_for_decision(
    app_client: AsyncClient,
) -> None:
    pair = await _pair()
    rec_h = await _headers(app_client, pair["recruiter"])
    created = await app_client.post(
        "/api/pre-contracts",
        headers=rec_h,
        json={"candidate_id": pair["candidate_id"], "job_id": pair["job_id"]},
    )
    request_id = created.json()["id"]
    early = await app_client.post(
        f"/api/pre-contracts/{request_id}/candidate-withdrew",
        headers=rec_h,
        json={"kind": "no_show", "event_on": "2026-10-28", "note": "Nie dołączył."},
    )
    assert early.status_code == 409

    doc_id = await _document(pair, valid_until=business_today() + timedelta(days=60))
    await app_client.post(
        f"/api/pre-contracts/{request_id}/document",
        headers=rec_h,
        json={"document_id": doc_id},
    )
    await app_client.post(
        f"/api/pre-contracts/{request_id}/candidate-signed",
        headers=rec_h,
        data={"signature_form": "handwritten_scan"},
        files={"file": ("skan.pdf", PDF, "application/pdf")},
    )
    await app_client.post(
        f"/api/pre-contracts/{request_id}/company-signed",
        headers=rec_h,
        files={"file": ("skan2.pdf", PDF, "application/pdf")},
    )
    resp = await app_client.post(
        f"/api/pre-contracts/{request_id}/candidate-withdrew",
        headers=rec_h,
        json={
            "kind": "no_show",
            "event_on": "2026-10-28",
            "note": "Nie dołączył.",
            # Rekruter wskazuje siebie — dostaje dzwonek, ale nie decyduje.
            "decision_user_id": pair["recruiter"][0],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == "candidate_withdrew"
    assert body["withdrawal"]["contract_state"]["in_force"] is True
    assert body["can_decide_penalty"] is False  # rekruter nie decyduje o karze

    listed = await app_client.get("/api/pre-contracts?tab=penalty", headers=rec_h)
    assert request_id in [i["id"] for i in listed.json()["items"]]

    decided = await app_client.post(
        f"/api/pre-contracts/{request_id}/penalty-decision",
        headers=rec_h,
        json={"decision": "waive"},
    )
    assert decided.status_code == 403


async def test_request_for_person_outside_the_job_is_refused(
    app_client: AsyncClient,
) -> None:
    pair = await _pair()
    other = await _pair()
    rec_h = await _headers(app_client, pair["recruiter"])
    resp = await app_client.post(
        "/api/pre-contracts",
        headers=rec_h,
        json={"candidate_id": other["candidate_id"], "job_id": pair["job_id"]},
    )
    assert resp.status_code == 409


async def test_client_acceptance_starts_b2b_deadline_for_signed_cez_contract() -> None:
    from app.services import pre_contracts

    pair = await _pair()
    async with AsyncSessionLocal() as db:
        doc = B2BContractDocument(
            document_type="preliminary_cez",
            language="pl",
            candidate_id=pair["candidate_id"],
            job_id=pair["job_id"],
            document_date=date(2026, 10, 21),
            render_payload={"values": {}},
            template_key="preliminary_cez_pl",
        )
        db.add(doc)
        await db.flush()
        now = pre_contracts.now_utc()
        req = PreContractRequest(
            candidate_id=pair["candidate_id"],
            job_id=pair["job_id"],
            needed_before="b2b_contract",
            requested_by=pair["dl"][0],
            assignee_id=pair["recruiter"][0],
            document_id=doc.id,
            sent_at=now,
            candidate_signed_at=now,
            company_signed_at=now,
        )
        db.add(req)
        await db.flush()
        await pre_contracts.add_watchers(db, req.id, [pair["dl"][0]])
        await pre_contracts.on_move(
            db,
            candidate_id=pair["candidate_id"],
            job_id=pair["job_id"],
            to_column="contract",
            to_label="Akceptacja i umowa",
            accepted_on=business_today(),
            actor_id=pair["recruiter"][0],
            actor_name="Rekruter",
        )
        await db.commit()
        request_id = req.id
    async with AsyncSessionLocal() as db:
        req = await db.get(PreContractRequest, request_id)
        # 5 dni roboczych od akceptacji (od dziś, gdy akceptacja jest dzisiejsza).
        expected = add_business_days(
            datetime.combine(business_today(), time(12), tzinfo=timezone.utc), 5
        )
        assert req.b2b_deadline == expected
    [bell] = await _bells(pair["dl"][0])
    assert f"{expected:%d.%m.%Y}" in bell.message


async def test_moving_past_needed_column_without_signature_tells_requester_once() -> (
    None
):
    from app.services import pre_contracts

    pair = await _pair()
    async with AsyncSessionLocal() as db:
        req = PreContractRequest(
            candidate_id=pair["candidate_id"],
            job_id=pair["job_id"],
            needed_before="cv_sent",
            requested_by=pair["dl"][0],
            assignee_id=pair["recruiter"][0],
        )
        db.add(req)
        await db.flush()
        await pre_contracts.add_watchers(db, req.id, [pair["dl"][0]])
        for column in ("cv_sent", "client_interview"):
            await pre_contracts.on_move(
                db,
                candidate_id=pair["candidate_id"],
                job_id=pair["job_id"],
                to_column=column,
                to_label=column,
                accepted_on=None,
                actor_id=pair["recruiter"][0],
                actor_name="Rekruter",
            )
        await db.commit()
    bells = await _bells(pair["dl"][0])
    assert len(bells) == 1
    assert "bez podpisanej umowy przedwstępnej" in bells[0].message


async def test_finance_outside_the_job_cannot_read_files_or_change_state(
    app_client: AsyncClient,
) -> None:
    pair = await _pair()
    rec_h = await _headers(app_client, pair["recruiter"])
    created = await app_client.post(
        "/api/pre-contracts",
        headers=rec_h,
        json={"candidate_id": pair["candidate_id"], "job_id": pair["job_id"]},
    )
    request_id = created.json()["id"]
    async with AsyncSessionLocal() as db:
        finance, pwd = await _user(db, UserRole.finance)
        await db.commit()
        who = (finance.id, finance.email, pwd)
    fin_h = await _headers(app_client, who)
    for method, url, body in (
        ("get", f"/api/pre-contracts/{request_id}", None),
        ("get", f"/api/pre-contracts/{request_id}/files/candidate", None),
        ("post", f"/api/pre-contracts/{request_id}/cancel", {"reason": "test test"}),
    ):
        resp = await getattr(app_client, method)(
            url, headers=fin_h, **({"json": body} if body else {})
        )
        assert resp.status_code == 403, (url, resp.status_code)


async def test_automation_account_cannot_open_pre_contract_files(
    app_client: AsyncClient,
) -> None:
    pair = await _pair()
    rec_h = await _headers(app_client, pair["recruiter"])
    created = await app_client.post(
        "/api/pre-contracts",
        headers=rec_h,
        json={"candidate_id": pair["candidate_id"], "job_id": pair["job_id"]},
    )
    async with AsyncSessionLocal() as db:
        bot, pwd = await _user(db, UserRole.automation)
        await db.commit()
        who = (bot.id, bot.email, pwd)
    resp = await app_client.get(
        f"/api/pre-contracts/{created.json()['id']}",
        headers=await _headers(app_client, who),
    )
    assert resp.status_code == 403


async def test_signing_after_client_acceptance_starts_b2b_deadline_from_today() -> None:
    from app.services import pre_contracts

    pair = await _pair()
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=pair["candidate_id"],
                job_id=pair["job_id"],
                stage=PipelineStage.acceptance,
                moved_by=pair["recruiter"][0],
                client_accepted_on=date(2026, 10, 1),
            )
        )
        doc = B2BContractDocument(
            document_type="preliminary_cez",
            language="pl",
            candidate_id=pair["candidate_id"],
            job_id=pair["job_id"],
            document_date=date(2026, 10, 1),
            render_payload={"values": {}},
            template_key="preliminary_cez_pl",
        )
        db.add(doc)
        await db.flush()
        now = pre_contracts.now_utc()
        req = PreContractRequest(
            candidate_id=pair["candidate_id"],
            job_id=pair["job_id"],
            needed_before="b2b_contract",
            requested_by=pair["dl"][0],
            assignee_id=pair["recruiter"][0],
            document_id=doc.id,
            sent_at=now,
            candidate_signed_at=now,
            company_signed_at=now,
        )
        db.add(req)
        await db.flush()
        accepted = await pre_contracts.latest_acceptance(
            db, candidate_id=pair["candidate_id"], job_id=pair["job_id"]
        )
        assert accepted == date(2026, 10, 1)
        await pre_contracts.start_b2b_deadline(
            db, req, accepted_on=accepted, actor_id=None
        )
        # Akceptacja sprzed podpisu: 5 dni roboczych liczone od dziś.
        assert req.b2b_deadline is not None
        assert req.b2b_deadline > business_today()
        await db.rollback()
