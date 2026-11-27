"""Masowa wysyłka nowej umowy B2B (E5b, 0757) — przebieg na bazie.

Podgląd i próba bez zapisu, blokada „nowy wzór podpięty” (409 i pętla nic
nie wysyła), paczka: wiersze Generatora drogą „Pobierz DOCX” (numer, plik,
powiązanie z kontraktem), wysyłka partiami drogą „Wyślij do podpisu”.

Maile są podmienione (nic nie wychodzi), Word → PDF też (``esign_env``).
Baza wspólna i nieczyszczona: asercje wyłącznie na własnych osobach. Dane
zmyślone.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, update

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.b2b_contract_detail import B2BContractDetail
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_mass_send import B2BMassSendBatch, B2BMassSendItem
from app.models.b2b_signing_request import B2BSigningRequest
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.b2b_esign import mail as esign_mail
from app.services.b2b_mass_send import readiness, service
from app.services.b2b_mass_send import settings as mass_settings
from app.tasks import b2b_mass_send as loop
from tests._krz import KRZ_CLEAR
from tests.test_b2b_esign import esign_env  # noqa: F401 — fikstura
from tests.test_b2b_signature_automation import _headers_for_role, _unique_number

URL = "/api/b2b-generator/mass-send"


# ── dane ─────────────────────────────────────────────────────────────────────


async def _seed_person(
    *,
    created_by: int,
    end_date: Optional[date] = None,
    email: bool = True,
    generator_row: bool = True,
    payload_overrides: Optional[dict[str, Any]] = None,
) -> dict[str, int]:
    """Aktywny kontrakt B2B z osobą w rekrutacji i (domyślnie) podpisaną
    umową z Generatora z kompletem danych."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Klient Masowy {unique}")
        address = f"masowa-{unique}@example.com" if email else None
        candidate = Candidate(
            name="Jan",
            lastname=f"Masowy-{unique}",
            email=address,
            created_by=created_by,
        )
        db.add_all([client, candidate])
        await db.flush()
        job = Job(
            title=f"Analityk {unique}", client_id=client.id, status=JobStatus.published
        )
        db.add(job)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job.id,
                stage=PipelineStage.onboarding,
                moved_by=created_by,
            )
        )
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            job_id=job.id,
            status=ContractStatus.active,
            contract_type=ContractType.b2b,
            start_date=date(2025, 3, 1),
            end_date=end_date,
            rate_candidate=Decimal("150.5"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            is_replacement=False,
            fte=Decimal("1"),
        )
        db.add(contract)
        await db.flush()
        generated_id = 0
        if generator_row:
            year, seq, number = _unique_number()
            payload: dict[str, Any] = {
                "candidate_id": candidate.id,
                "job_id": job.id,
                "role_id": None,
                "scope_items_override": ["Analiza wymagań systemu."],
                "language": "pl",
                "gender": "m",
                "partner_name": f"Jan Masowy-{unique}",
                "partner_instrumental": f"Janem Masowym-{unique}",
                "partner_legal_name": f"Jan Masowy {unique} Usługi",
                "partner_nip": "1234563218",
                "partner_regon": "123456785",
                "partner_business_address": "ul. Przykładowa 1, 00-001 Warszawa",
                "partner_email": address,
                "partner_phone": "+48 600 000 000",
                "client_name": client.name,
                "project_city": "Warszawa",
                "project_description": "Rozwój systemu.",
                "contract_number": number,
                "signing_date": "2025-02-20",
                "start_date": "2025-03-01",
                "rate_candidate": 150.5,
                "currency": "PLN",
                "is_replacement": False,
                "fte": "1",
                **(payload_overrides or {}),
            }
            row = B2BGeneratedContract(
                krz_check=KRZ_CLEAR,
                year=year,
                seq=seq,
                contract_number=number,
                partner_name=payload["partner_name"],
                client_name=client.name,
                language="pl",
                signing_date=date(2025, 2, 20),
                created_by=created_by,
                candidate_id=candidate.id,
                job_id=job.id,
                client_id=client.id,
                contract_id=contract.id,
                contract_status="active",
                signature_status="signed_both",
                render_payload=payload,
            )
            db.add(row)
            await db.flush()
            generated_id = row.id
        await db.commit()
        return {
            "candidate_id": candidate.id,
            "contract_id": contract.id,
            "job_id": job.id,
            "client_id": client.id,
            "generated_id": generated_id,
        }


async def _open_request_for(person: dict[str, int], *, created_by: int) -> int:
    """Niepodpisany wiersz tej osoby w podpisie w NEXUSIE (wniosek ``sent``)."""
    year, seq, number = _unique_number()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        row = B2BGeneratedContract(
            krz_check=KRZ_CLEAR,
            year=year,
            seq=seq,
            contract_number=number,
            partner_name="Jan Masowy",
            language="pl",
            created_by=created_by,
            candidate_id=person["candidate_id"],
            job_id=person["job_id"],
            client_id=person["client_id"],
            contract_status="in_progress",
            signature_status="unsigned",
            render_payload={"partner_name": "Jan Masowy"},
        )
        db.add(row)
        await db.flush()
        request = B2BSigningRequest(
            generated_contract_id=row.id,
            status="sent",
            contractor_name="Jan Masowy",
            contractor_email="masowy@example.com",
            source_pdf_path="b2b_signing/test.pdf",
            source_sha256="0" * 64,
            source_size=10,
            sent_by=created_by,
            sent_at=now,
            expires_at=now + timedelta(days=3),
        )
        db.add(request)
        await db.commit()
        return request.id


async def _rows_of(candidate_id: int) -> list[B2BGeneratedContract]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(B2BGeneratedContract)
                    .where(B2BGeneratedContract.candidate_id == candidate_id)
                    .order_by(B2BGeneratedContract.id)
                )
            ).all()
        )


async def _items_of(candidate_id: int) -> list[B2BMassSendItem]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(B2BMassSendItem)
                    .where(B2BMassSendItem.candidate_id == candidate_id)
                    .order_by(B2BMassSendItem.id)
                )
            ).all()
        )


async def _set_ready(value: bool, actor_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await mass_settings.save(
            db, template_ready=value, actor_id=actor_id, now=datetime.now(timezone.utc)
        )
        await db.commit()


async def _preview_row(
    app_client: AsyncClient, headers: dict[str, str], candidate_id: int
) -> Optional[dict[str, Any]]:
    offset = 0
    while True:
        response = await app_client.get(
            f"{URL}/preview",
            params={"offset": offset, "limit": 200},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        for row in body["rows"]:
            if row["candidate_id"] == candidate_id:
                return row
        offset += 200
        if offset >= body["rows_total"]:
            return None


@pytest.fixture
async def mass_env(monkeypatch, app_client: AsyncClient, esign_env):  # noqa: F811
    """Podpis w NEXUSIE włączony, pętla włączona, maile podmienione."""
    from app.api import b2b_mass_send as api
    from app.core.config import settings as config

    mails: list[dict[str, Any]] = []

    async def _connected(db, user_id):
        return True

    async def _send_from(db, **kwargs):
        mails.append(kwargs)
        return True, None

    monkeypatch.setattr(config, "B2B_MASS_SEND_ENABLED", True)
    monkeypatch.setattr(api.app_config, "B2B_MASS_SEND_ENABLED", True)
    monkeypatch.setattr(esign_mail, "mailbox_connected", _connected)
    monkeypatch.setattr(esign_mail, "send_from", _send_from)
    await _set_ready(False, esign_env["admin_id"])
    yield {**esign_env, "mails": mails}
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(B2BMassSendItem)
            .where(B2BMassSendItem.status.in_(("pending", "created")))
            .values(status="skipped", reason="cancelled")
        )
        await db.execute(
            update(B2BMassSendBatch)
            .where(B2BMassSendBatch.status == "running")
            .values(status="cancelled")
        )
        await db.commit()
    await _set_ready(False, esign_env["admin_id"])


def _start_body(signer_id: int, days: int = 7) -> dict[str, Any]:
    return {"skip_ending": True, "company_signer_id": signer_id, "days": days}


# ── podgląd i próba ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_preview_gives_each_person_a_state_and_writes_nothing(
    app_client: AsyncClient, app_auth_headers: dict[str, str], mass_env
):
    admin = mass_env["admin_id"]
    ready = await _seed_person(created_by=admin)
    ending = await _seed_person(
        created_by=admin, end_date=business_today() + timedelta(days=10)
    )
    no_email = await _seed_person(
        created_by=admin, email=False, payload_overrides={"partner_email": None}
    )
    no_data = await _seed_person(created_by=admin, generator_row=False)
    missing = await _seed_person(
        created_by=admin, payload_overrides={"project_city": "", "partner_regon": None}
    )
    in_signing = await _seed_person(created_by=admin)
    await _open_request_for(in_signing, created_by=admin)

    async with AsyncSessionLocal() as db:
        rows_before = await db.scalar(select(func.count(B2BGeneratedContract.id)))

    expected = {
        ready["candidate_id"]: ("ready", None),
        ending["candidate_id"]: ("skipped", readiness.REASON_ENDING),
        no_email["candidate_id"]: ("skipped", readiness.REASON_NO_EMAIL),
        no_data["candidate_id"]: ("skipped", readiness.REASON_NO_PARTNER_DATA),
        missing["candidate_id"]: ("needs_review", readiness.REASON_MISSING),
        in_signing["candidate_id"]: ("skipped", readiness.REASON_OPEN_REQUEST),
    }
    for candidate_id, (status, reason) in expected.items():
        row = await _preview_row(app_client, app_auth_headers, candidate_id)
        assert row is not None, candidate_id
        assert (row["status"], row["reason"]) == (status, reason), row
    missing_row = await _preview_row(
        app_client, app_auth_headers, missing["candidate_id"]
    )
    assert set(missing_row["missing"]) == {"Miasto Klienta", "REGON"}

    preview = await app_client.get(
        f"{URL}/preview", params={"limit": 1}, headers=app_auth_headers
    )
    body = preview.json()
    assert no_email["candidate_id"] in {p["id"] for p in body["no_email"]}
    assert body["summary"]["ending_soon"] >= 1
    clients = {c["client_id"]: c for c in body["summary"]["by_client"]}
    assert clients[ready["client_id"]] == {
        "client_id": ready["client_id"],
        "client_name": clients[ready["client_id"]]["client_name"],
        "total": 1,
        "ready": 1,
    }
    # Pole odznaczone: osoba z końcem umowy wraca do gotowych.
    kept = await app_client.get(
        f"{URL}/preview",
        params={"skip_ending": "false", "status": "ready", "limit": 200},
        headers=app_auth_headers,
    )
    assert kept.status_code == 200
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(select(func.count(B2BGeneratedContract.id))) == rows_before
        )
        assert (
            await db.scalar(
                select(func.count(B2BMassSendItem.id)).where(
                    B2BMassSendItem.candidate_id == ready["candidate_id"]
                )
            )
            == 0
        )


@pytest.mark.asyncio
async def test_preview_shows_only_people_the_caller_could_send(
    app_client: AsyncClient, mass_env
):
    person = await _seed_person(created_by=mass_env["admin_id"])
    recruiter = await _headers_for_role(app_client, UserRole.recruiter)
    response = await app_client.get(
        f"{URL}/preview", params={"limit": 200}, headers=recruiter
    )
    assert response.status_code == 200, response.text
    assert person["candidate_id"] not in {
        r["candidate_id"] for r in response.json()["rows"]
    }


@pytest.mark.asyncio
async def test_dry_run_works_while_blocked_and_uses_no_number(
    app_client: AsyncClient, app_auth_headers: dict[str, str], mass_env
):
    person = await _seed_person(created_by=mass_env["admin_id"])
    broken = await _seed_person(created_by=mass_env["admin_id"])
    # Osoba wypadła z rekrutacji: plan jej nie odrzuca, Generator tak (409).
    async with AsyncSessionLocal() as db:
        await db.execute(
            CandidateStage.__table__.delete().where(
                CandidateStage.candidate_id == broken["candidate_id"]
            )
        )
        await db.commit()
    number_before = (
        await app_client.get("/api/b2b-generator/next-number", headers=app_auth_headers)
    ).json()["contract_number"]

    response = await app_client.post(
        f"{URL}/dry-run", json={"skip_ending": True}, headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["blocked"] is True
    assert service.MSG_TEMPLATE_NOT_READY in body["block_reasons"]
    problems = {p["candidate_id"]: p for p in body["problems"]}
    assert broken["candidate_id"] in problems
    assert person["candidate_id"] not in problems
    assert any(
        "nie uczestniczy" in i for i in problems[broken["candidate_id"]]["issues"]
    )
    number_after = (
        await app_client.get("/api/b2b-generator/next-number", headers=app_auth_headers)
    ).json()["contract_number"]
    assert number_after == number_before
    assert len(await _rows_of(person["candidate_id"])) == 1
    assert await _items_of(person["candidate_id"]) == []


# ── blokada „nowy wzór podpięty” ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_endpoint_is_409_until_the_new_template_is_ready(
    app_client: AsyncClient, app_auth_headers: dict[str, str], mass_env
):
    person = await _seed_person(created_by=mass_env["admin_id"])
    blocked = await app_client.post(
        f"{URL}/batches",
        json=_start_body(mass_env["signer_id"]),
        headers=app_auth_headers,
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["detail"] == service.MSG_TEMPLATE_NOT_READY
    assert await _items_of(person["candidate_id"]) == []

    settings_view = await app_client.get(f"{URL}/settings", headers=app_auth_headers)
    assert settings_view.json()["template_ready"] is False


@pytest.mark.asyncio
async def test_only_an_admin_marks_the_new_template_as_ready(
    app_client: AsyncClient, app_auth_headers: dict[str, str], mass_env
):
    recruiter = await _headers_for_role(app_client, UserRole.recruiter)
    refused = await app_client.put(
        f"{URL}/settings", json={"template_ready": True}, headers=recruiter
    )
    assert refused.status_code == 403
    marked = await app_client.put(
        f"{URL}/settings", json={"template_ready": True}, headers=app_auth_headers
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["template_ready"] is True
    assert marked.json()["template_ready_by"]


@pytest.mark.asyncio
async def test_loop_sends_nothing_while_the_template_is_not_ready(
    app_client: AsyncClient, app_auth_headers: dict[str, str], mass_env
):
    person = await _seed_person(created_by=mass_env["admin_id"])
    await _set_ready(True, mass_env["admin_id"])
    started = await app_client.post(
        f"{URL}/batches",
        json=_start_body(mass_env["signer_id"]),
        headers=app_auth_headers,
    )
    assert started.status_code == 200, started.text
    # Admin cofa „nowy wzór podpięty”, zanim pętla ruszy.
    await _set_ready(False, mass_env["admin_id"])
    assert await loop.run_cycle() == {"blocked": 1}
    (item,) = await _items_of(person["candidate_id"])
    async with AsyncSessionLocal() as db:
        assert await service.process_item(db, item.id) is None
    (item,) = await _items_of(person["candidate_id"])
    assert item.status == "pending"
    assert item.generated_contract_id is None
    assert len(await _rows_of(person["candidate_id"])) == 1
    assert mass_env["mails"] == []


# ── paczka ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_batch_makes_generator_rows_and_sends_in_chunks(
    app_client: AsyncClient, app_auth_headers: dict[str, str], mass_env
):
    admin = mass_env["admin_id"]
    people = [await _seed_person(created_by=admin) for _ in range(3)]
    missing = await _seed_person(created_by=admin, payload_overrides={"fte": None})
    in_signing = await _seed_person(created_by=admin)
    await _open_request_for(in_signing, created_by=admin)
    await _set_ready(True, admin)

    started = await app_client.post(
        f"{URL}/batches",
        json=_start_body(mass_env["signer_id"]),
        headers=app_auth_headers,
    )
    assert started.status_code == 200, started.text
    batch = started.json()
    assert batch["status"] == "running"
    assert batch["template_label"] == service.TEMPLATE_LABEL

    (review,) = await _items_of(missing["candidate_id"])
    assert review.status == "needs_review"
    assert review.missing == ["Wymiar FTE"]
    (skipped,) = await _items_of(in_signing["candidate_id"])
    assert (skipped.status, skipped.reason) == (
        "skipped",
        readiness.REASON_OPEN_REQUEST,
    )

    # Druga paczka w trakcie pierwszej — odmowa, bez dublowania osób.
    again = await app_client.post(
        f"{URL}/batches",
        json=_start_body(mass_env["signer_id"]),
        headers=app_auth_headers,
    )
    assert again.status_code == 409

    # Partia: jeden bieg pętli przechodzi najwyżej ``limit`` pozycji.
    first = await loop.run_cycle(limit=2)
    assert sum(first.values()) == 2, first
    async with AsyncSessionLocal() as db:
        pending = await db.scalar(
            select(func.count(B2BMassSendItem.id)).where(
                B2BMassSendItem.batch_id == batch["id"],
                B2BMassSendItem.status.in_(("pending", "created")),
            )
        )
    assert pending >= 1
    for _ in range(20):
        if await loop.run_cycle(limit=50) in ({}, {"stopped": 1}):
            break

    for person in people:
        (item,) = await _items_of(person["candidate_id"])
        assert item.status == "sent", (item.status, item.error)
        rows = await _rows_of(person["candidate_id"])
        assert len(rows) == 2
        old, new = rows
        assert new.id == item.generated_contract_id
        assert new.contract_number != old.contract_number
        assert new.contract_id == person["contract_id"]
        assert new.previous_generated_contract_id == old.id
        assert new.created_by == admin
        assert new.contract_status == "in_progress"
        assert new.signing_date == business_today()
        assert (new.render_payload or {})["rate_candidate"] == 150.5
        async with AsyncSessionLocal() as db:
            # Niepodpisana umowa nie stempluje numeru w szczegółach B2B kontraktu.
            assert (
                await db.scalar(
                    select(B2BContractDetail.id).where(
                        B2BContractDetail.contract_id == person["contract_id"]
                    )
                )
                is None
            )
            request = await db.get(B2BSigningRequest, item.signing_request_id)
            assert request is not None and request.status == "sent"
            assert request.company_signer_id == mass_env["signer_id"]
            assert request.sent_by == admin
            assert (request.expires_at - request.sent_at).days == 7
    # Bez nowego wiersza dla osoby do sprawdzenia i osoby w podpisie.
    assert len(await _rows_of(missing["candidate_id"])) == 1
    # Wiersz z Generatora i wiersz w podpisie — nic nowego.
    assert len(await _rows_of(in_signing["candidate_id"])) == 2
    recipients = {mail["to"] for mail in mass_env["mails"]}
    for person in people:
        async with AsyncSessionLocal() as db:
            candidate = await db.get(Candidate, person["candidate_id"])
        assert candidate.email in recipients
    assert all(mail["user_id"] == admin for mail in mass_env["mails"])

    view = await app_client.get(
        f"{URL}/batches/{batch['id']}", headers=app_auth_headers
    )
    assert view.status_code == 200
    progress = view.json()["progress"]
    assert progress["sent"] >= 3
    assert progress["waiting_contractor"] >= 3
    assert view.json()["status"] == "finished"

    # Kolejna paczka: kto dostał link, nie dostaje drugiej umowy.
    async with AsyncSessionLocal() as db:
        admin_user = await db.get(User, admin)
        (second,) = await service.collect(
            db,
            admin_user,
            today=business_today(),
            skip_ending=True,
            candidate_ids=[people[0]["candidate_id"]],
        )
    assert second.assessment.reason == readiness.REASON_OPEN_REQUEST


@pytest.mark.asyncio
async def test_without_a_mailbox_the_item_fails_with_that_reason(
    monkeypatch, app_client: AsyncClient, app_auth_headers: dict[str, str], mass_env
):
    person = await _seed_person(created_by=mass_env["admin_id"])
    await _set_ready(True, mass_env["admin_id"])
    started = await app_client.post(
        f"{URL}/batches",
        json=_start_body(mass_env["signer_id"]),
        headers=app_auth_headers,
    )
    assert started.status_code == 200, started.text

    async def _disconnected(db, user_id):
        return False

    monkeypatch.setattr(esign_mail, "mailbox_connected", _disconnected)
    (item,) = await _items_of(person["candidate_id"])
    async with AsyncSessionLocal() as db:
        assert await service.process_item(db, item.id) == "failed"
    (item,) = await _items_of(person["candidate_id"])
    assert item.error == service.MSG_NO_MAILBOX
    assert item.signing_request_id is None
    async with AsyncSessionLocal() as db:
        opened = await db.scalar(
            select(func.count(B2BSigningRequest.id)).where(
                B2BSigningRequest.generated_contract_id == item.generated_contract_id
            )
        )
    assert opened == 0


@pytest.mark.asyncio
async def test_failed_mail_withdraws_the_request_of_that_person(
    monkeypatch, app_client: AsyncClient, app_auth_headers: dict[str, str], mass_env
):
    person = await _seed_person(created_by=mass_env["admin_id"])
    await _set_ready(True, mass_env["admin_id"])
    started = await app_client.post(
        f"{URL}/batches",
        json=_start_body(mass_env["signer_id"]),
        headers=app_auth_headers,
    )
    assert started.status_code == 200, started.text

    async def _bounced(db, **kwargs):
        return False, esign_mail.MSG_FAILED

    monkeypatch.setattr(esign_mail, "send_from", _bounced)
    (item,) = await _items_of(person["candidate_id"])
    async with AsyncSessionLocal() as db:
        assert await service.process_item(db, item.id) == "failed"
    (item,) = await _items_of(person["candidate_id"])
    assert item.error and item.error.startswith(service.MSG_MAIL_FAILED)
    async with AsyncSessionLocal() as db:
        request = await db.get(B2BSigningRequest, item.signing_request_id)
    assert request is not None and request.status == "withdrawn"


@pytest.mark.asyncio
async def test_cancel_stops_people_who_have_no_link_yet(
    app_client: AsyncClient, app_auth_headers: dict[str, str], mass_env
):
    person = await _seed_person(created_by=mass_env["admin_id"])
    await _set_ready(True, mass_env["admin_id"])
    started = await app_client.post(
        f"{URL}/batches",
        json=_start_body(mass_env["signer_id"]),
        headers=app_auth_headers,
    )
    assert started.status_code == 200, started.text
    cancelled = await app_client.post(
        f"{URL}/batches/{started.json()['id']}/cancel", headers=app_auth_headers
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    (item,) = await _items_of(person["candidate_id"])
    assert (item.status, item.error) == ("skipped", service.MSG_CANCELLED)
    assert len(await _rows_of(person["candidate_id"])) == 1
