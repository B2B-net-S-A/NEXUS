"""Umowa przedwstępna przy osobie w rekrutacji — API (0506, 21.10.2026).

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


@pytest.mark.parametrize(
    "role", [UserRole.finance, UserRole.automation, UserRole.board]
)
async def test_finance_board_and_automation_work_on_pre_contracts_like_a_recruiter(
    app_client: AsyncClient, role: UserRole
) -> None:
    # F54 (decyzja Artura 22.10.2026): Finanse, Rada nadzorcza i Automatyzacje
    # mają przedwstępne jak rekruter — odczyt, pliki i akcje, także w
    # rekrutacji, w której nie są w zespole.
    pair = await _pair()
    rec_h = await _headers(app_client, pair["recruiter"])
    created = await app_client.post(
        "/api/pre-contracts",
        headers=rec_h,
        json={"candidate_id": pair["candidate_id"], "job_id": pair["job_id"]},
    )
    request_id = created.json()["id"]
    async with AsyncSessionLocal() as db:
        account, pwd = await _user(db, role)
        await db.commit()
        who = (account.id, account.email, pwd)
    headers = await _headers(app_client, who)
    pair_view = await app_client.get(
        "/api/pre-contracts/pair",
        headers=headers,
        params={"candidate_id": pair["candidate_id"], "job_id": pair["job_id"]},
    )
    assert pair_view.status_code == 200, pair_view.text
    assert pair_view.json()["current"]["id"] == request_id
    one = await app_client.get(f"/api/pre-contracts/{request_id}", headers=headers)
    assert one.status_code == 200, one.text
    # Pliku jeszcze nie ma — 404 z treści, nie 403 z bramki.
    file_resp = await app_client.get(
        f"/api/pre-contracts/{request_id}/files/candidate", headers=headers
    )
    assert file_resp.status_code == 404, file_resp.text
    cancel = await app_client.post(
        f"/api/pre-contracts/{request_id}/cancel",
        headers=headers,
        json={"reason": "test test"},
    )
    assert cancel.status_code == 200, cancel.text


async def test_viewer_cannot_open_pre_contracts(app_client: AsyncClient) -> None:
    pair = await _pair()
    async with AsyncSessionLocal() as db:
        viewer, pwd = await _user(db, UserRole.user)
        await db.commit()
        who = (viewer.id, viewer.email, pwd)
    resp = await app_client.get(
        "/api/pre-contracts/pair",
        headers=await _headers(app_client, who),
        params={"candidate_id": pair["candidate_id"], "job_id": pair["job_id"]},
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
        # Tak woła ścieżka podpisu firmy (`company_signed`).
        await pre_contracts.start_b2b_deadline(
            db, req, accepted_on=accepted, actor_id=None, from_today=True
        )
        # Akceptacja sprzed podpisu: 5 dni roboczych liczone od dziś.
        assert req.b2b_deadline is not None
        assert req.b2b_deadline > business_today()
        await db.rollback()


# ── Audyt 22.10.2026 ─────────────────────────────────────────────────────────


async def _issued_and_sent(app_client: AsyncClient, pair: dict, headers) -> tuple:
    created = await app_client.post(
        "/api/pre-contracts",
        headers=headers,
        json={"candidate_id": pair["candidate_id"], "job_id": pair["job_id"]},
    )
    request_id = created.json()["id"]
    doc_id = await _document(pair, valid_until=business_today() + timedelta(days=60))
    linked = await app_client.post(
        f"/api/pre-contracts/{request_id}/document",
        headers=headers,
        json={"document_id": doc_id},
    )
    assert linked.status_code == 200, linked.text
    sent = await app_client.post(
        f"/api/pre-contracts/{request_id}/sent", headers=headers, json={}
    )
    assert sent.status_code == 200, sent.text
    return request_id, doc_id, sent.json()


async def test_stale_screen_cannot_swap_document_or_move_sent_date(
    app_client: AsyncClient,
) -> None:
    # F105: „Podepnij umowę” i „Oznacz jako wysłaną” ze starego ekranu nie
    # podmieniają dokumentu ani daty wysyłki, gdy umowa poszła dalej.
    pair = await _pair()
    rec_h = await _headers(app_client, pair["recruiter"])
    request_id, doc_id, sent = await _issued_and_sent(app_client, pair, rec_h)
    other_doc = await _document(pair, valid_until=business_today() + timedelta(days=5))

    swap = await app_client.post(
        f"/api/pre-contracts/{request_id}/document",
        headers=rec_h,
        json={"document_id": other_doc},
    )
    assert swap.status_code == 409, swap.text

    again = await app_client.post(
        f"/api/pre-contracts/{request_id}/sent", headers=rec_h, json={}
    )
    assert again.status_code == 200, again.text
    assert again.json()["sent_at"] == sent["sent_at"]

    signed = await app_client.post(
        f"/api/pre-contracts/{request_id}/candidate-signed",
        headers=rec_h,
        data={"signature_form": "trusted_profile"},
        files={"file": ("umowa.pdf", PDF, "application/pdf")},
    )
    assert signed.status_code == 200, signed.text
    after = await app_client.post(
        f"/api/pre-contracts/{request_id}/sent", headers=rec_h, json={}
    )
    assert after.status_code == 409, after.text

    body = (
        await app_client.get(f"/api/pre-contracts/{request_id}", headers=rec_h)
    ).json()
    assert body["document_id"] == doc_id
    assert body["valid_until"] == sent["valid_until"]
    assert body["sent_at"] == sent["sent_at"]
    assert [e["kind"] for e in body["events"]].count("sent") == 1
    assert [e["kind"] for e in body["events"]].count("issued") == 1


async def test_candidate_withdrawal_rings_head_of_recruitment_and_named_person(
    app_client: AsyncClient,
) -> None:
    # F50: o karze decyduje Head of Recruitment — dostaje dzwonek, choć nie
    # obserwuje prośby; wskazana osoba też (dopisana przed dzwonkiem).
    pair = await _pair()
    rec_h = await _headers(app_client, pair["recruiter"])
    async with AsyncSessionLocal() as db:
        hor, _ = await _user(db, UserRole.head_of_recruitment)
        named, _ = await _user(db, UserRole.delivery_lead)
        await db.commit()
        hor_id, named_id = hor.id, named.id
    request_id, _doc, _sent = await _issued_and_sent(app_client, pair, rec_h)
    await app_client.post(
        f"/api/pre-contracts/{request_id}/candidate-signed",
        headers=rec_h,
        data={"signature_form": "qualified"},
        files={"file": ("k.pdf", PDF, "application/pdf")},
    )
    await app_client.post(
        f"/api/pre-contracts/{request_id}/company-signed",
        headers=rec_h,
        files={"file": ("f.pdf", PDF, "application/pdf")},
    )
    resp = await app_client.post(
        f"/api/pre-contracts/{request_id}/candidate-withdrew",
        headers=rec_h,
        json={
            "kind": "resigned",
            "event_on": business_today().isoformat(),
            "note": "Zrezygnował po teście.",
            "decision_user_id": named_id,
        },
    )
    assert resp.status_code == 200, resp.text
    for uid in (hor_id, named_id):
        bells = await _bells(uid)
        assert [b for b in bells if "decyzja o karze" in b.message], uid


async def test_list_shows_the_latest_step_of_each_request(
    app_client: AsyncClient,
) -> None:
    # F52: kolumna „Ostatni krok” na liście potrzebuje ostatniego zdarzenia.
    pair = await _pair()
    rec_h = await _headers(app_client, pair["recruiter"])
    request_id, _doc, _sent = await _issued_and_sent(app_client, pair, rec_h)
    listed = await app_client.get("/api/pre-contracts?tab=all", headers=rec_h)
    assert listed.status_code == 200, listed.text
    [row] = [i for i in listed.json()["items"] if i["id"] == request_id]
    assert [e["kind"] for e in row["events"]] == ["sent"]
    assert row["events"][0]["actor"]["id"] == pair["recruiter"][0]
