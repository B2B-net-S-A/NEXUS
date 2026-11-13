"""Paczka do podpisu (0687, decyzja Artura 13.11.2026): umowa B2B i wzory
z listy klienta „Dokumenty do startu” pod jednym linkiem.

Kontraktor podpisuje wszystko za jednym razem; umowa idzie do reprezentanta
B2B Network dopiero po ostatnim dokumencie, a podpisany dokument od razu
odhacza pozycję pary. Przebieg na bazie korzysta z ``esign_env``
z ``test_b2b_esign.py`` (walidator i zamiana Worda na PDF podmienione).
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.services.b2b_esign import mail as esign_mail
from app.services.b2b_esign import service
from app.services.b2b_esign.history import esign_history
from tests.test_b2b_esign import (  # noqa: F401 — fikstura esign_env
    SOURCE,
    _FakeValidator,
    _partner,
    _report,
    _seed_in_progress,
    _token,
    esign_env,
)

NDA = b"%PDF-1.7\n% NDA klienta\n%%EOF\n"


# ── czyste reguły ────────────────────────────────────────────────────────────


def test_link_mail_lists_the_contract_and_every_document_of_the_package():
    subject, body = esign_mail.contractor_sign_message(
        number="1557/2026",
        url="https://nexus.example/sign/b2b/t",
        expires_at=datetime(2026, 11, 20, 12, tzinfo=timezone.utc),
        documents=["NDA Nordea", "Oświadczenie o niekaralności"],
    )
    assert subject == "Umowa B2B nr 1557/2026 i dokumenty do podpisu"
    for name in (
        "Umowa B2B nr 1557/2026",
        "NDA Nordea",
        "Oświadczenie o niekaralności",
    ):
        assert name in body
    assert "Otwórz dokumenty do podpisu" in body
    assert "—" not in body


def test_link_mail_without_documents_stays_as_it_was():
    subject, body = esign_mail.contractor_sign_message(
        number="1557/2026",
        url="https://nexus.example/sign/b2b/t",
        expires_at=datetime(2026, 11, 20, 12, tzinfo=timezone.utc),
    )
    assert subject == "Umowa B2B nr 1557/2026 do podpisu"
    assert "Otwórz umowę do podpisu" in body


class _Request:
    def __init__(self, **values: Any) -> None:
        self.events = values.pop("events", [])
        self.contractor_signed_at = values.pop("contractor_signed_at", None)
        for key, value in values.items():
            setattr(self, key, value)


def test_contract_day_is_the_contract_signature_not_the_last_document():
    contract = datetime(2026, 11, 30, 22, tzinfo=timezone.utc)
    last_doc = datetime(2026, 12, 2, 9, tzinfo=timezone.utc)
    request = _Request(
        events=[{"kind": "contract_signed", "at": contract.isoformat()}],
        contractor_signed_at=last_doc,
    )
    assert service.contract_signed_at(request) == contract
    plain = _Request(contractor_signed_at=last_doc)
    assert service.contract_signed_at(plain) == last_doc


def test_history_names_each_signed_document():
    now = datetime(2026, 11, 13, 10, tzinfo=timezone.utc)
    request = _Request(
        id=7,
        sent_at=now,
        sent_by=1,
        last_reminder_at=None,
        status="sent",
        completed_at=None,
        closed_at=None,
        close_reason=None,
        company_signer_id=None,
        closed_by=None,
        events=[
            {"kind": "contract_signed", "at": now.isoformat()},
            {
                "kind": "document_signed",
                "at": (now + timedelta(minutes=5)).isoformat(),
                "title": "NDA Nordea",
            },
        ],
    )
    labels = [e.label for e in esign_history([request])]
    assert "Kontraktor podpisał umowę, czekają pozostałe dokumenty" in labels
    assert "Kontraktor podpisał: NDA Nordea" in labels


def test_entrypoint_mirrors_the_package_table():
    root = Path(__file__).resolve().parents[1]
    entrypoint = (root / "entrypoint.sh").read_text(encoding="utf-8")
    assert "documents_schema as _b2b_signing_documents_schema" in entrypoint
    assert "*_B2B_SIGNING_DOCUMENTS_DDL," in entrypoint
    # Po tabelach, na które wskazują klucze obce.
    assert entrypoint.index("*_B2B_SIGNING_DOCUMENTS_DDL,") > entrypoint.index(
        "CREATE TABLE IF NOT EXISTS b2b_signing_requests"
    )
    assert entrypoint.index("*_B2B_SIGNING_DOCUMENTS_DDL,") > entrypoint.index(
        "*_START_DOCUMENTS_TABLE_DDL,"
    )
    migration = (root / "alembic/versions/0687_b2b_signing_documents.py").read_text()
    assert re.search(r'down_revision = "0686_autofill_gaps_round4"', migration)


# ── przebieg na bazie ────────────────────────────────────────────────────────


async def _client_template(client_id: int, name: str, data: bytes) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.start_document import ClientStartDocument
    from app.services import storage_service

    path, _ = storage_service.save_start_document_file(
        f"clients/{client_id}", f"{name}.pdf", data
    )
    async with AsyncSessionLocal() as db:
        item = ClientStartDocument(
            client_id=client_id,
            position=1,
            name=name,
            kind="file",
            template_path=path,
            template_name=f"{name}.pdf",
            template_content_type="application/pdf",
        )
        db.add(item)
        await db.commit()
        return item.id


async def _send(app_client, headers, generated_id: int, signer_id: int, **extra):
    return await app_client.post(
        f"/api/b2b-generator/generated/{generated_id}/esign/send",
        json={
            "contractor_email": "anna@example.com",
            "company_signer_id": signer_id,
            "days": 7,
            **extra,
        },
        headers=headers,
    )


async def _use_admin_as_company_signer(admin_id: int) -> None:
    from app.core.database import AsyncSessionLocal
    from app.services.b2b_esign import settings as esign_settings

    async with AsyncSessionLocal() as db:
        await esign_settings.save(
            db,
            esign_settings.EsignSettings(mode="all", company_signer_ids=(admin_id,)),
            actor_id=admin_id,
        )
        await db.commit()


@pytest.mark.asyncio
async def test_contractor_signs_the_contract_and_the_nda_on_one_link(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    esign_env,  # noqa: F811
):
    from app.core.database import AsyncSessionLocal
    from app.core.scheduling import business_date
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.b2b_signing_request import B2BSigningRequest
    from app.models.start_document import PlacementStartDocument
    from app.models.user import User
    from app.services import storage_service
    from sqlalchemy import select

    admin_id = esign_env["admin_id"]
    await _use_admin_as_company_signer(admin_id)
    scenario = await _seed_in_progress(created_by=admin_id)
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        row.created_at = datetime.now(timezone.utc) - timedelta(days=10)
        await db.commit()
    nda_id = await _client_template(scenario["client_id"], "NDA klienta", NDA)
    partner = await _partner(scenario["generated_id"])

    defaults = await app_client.get(
        f"/api/b2b-generator/generated/{scenario['generated_id']}/esign/defaults",
        headers=app_auth_headers,
    )
    assert defaults.status_code == 200, defaults.text
    assert defaults.json()["documents"] == [{"id": nda_id, "name": "NDA klienta"}]

    sent = await _send(app_client, app_auth_headers, scenario["generated_id"], admin_id)
    assert sent.status_code == 200, sent.text
    request_id = sent.json()["request"]["id"]
    [document] = sent.json()["request"]["documents"]
    assert document["title"] == "NDA klienta" and document["signed_at"] is None
    token = _token(sent.json()["sign_url"])

    view = (await app_client.get(f"/api/public/b2b-sign/{token}")).json()
    assert view["status"] == "waiting" and view["contract_signed"] is False
    assert view["documents"] == [
        {"id": document["id"], "title": "NDA klienta", "signed": False}
    ]
    nda_pdf = await app_client.get(
        f"/api/public/b2b-sign/{token}/documents/{document['id']}/pdf"
    )
    assert nda_pdf.status_code == 200 and nda_pdf.content == NDA

    # Umowa podpisana pierwsza: link dalej czeka na NDA, firma jeszcze nic nie ma.
    _FakeValidator.report = _report((f"CN={partner}", "TOTAL_PASSED", "QESig"))
    contract_pdf = SOURCE + b"% podpis kontraktora\n"
    signed = await app_client.post(
        f"/api/public/b2b-sign/{token}",
        files={"file": ("u.pdf", contract_pdf, "application/pdf")},
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "waiting"
    assert signed.json()["contract_signed"] is True
    twice = await app_client.post(
        f"/api/public/b2b-sign/{token}",
        files={"file": ("u.pdf", contract_pdf, "application/pdf")},
    )
    assert twice.status_code == 409, twice.text
    mine = await app_client.get(
        "/api/b2b-generator/esign/mine", headers=app_auth_headers
    )
    assert request_id not in [r["id"] for r in mine.json()]

    # NDA bez podpisu kontraktora nie przejdzie.
    _FakeValidator.report = _report(("CN=Jan Obcy", "TOTAL_PASSED", "QESig"))
    stranger = await app_client.post(
        f"/api/public/b2b-sign/{token}/documents/{document['id']}",
        files={"file": ("n.pdf", NDA + b"% podpis\n", "application/pdf")},
    )
    assert stranger.status_code == 422, stranger.text

    # Dzień podpisu umowy ma zostać dniem umowy, nie NDA wgranego później.
    async with AsyncSessionLocal() as db:
        request = await db.get(B2BSigningRequest, request_id)
        earlier = datetime.now(timezone.utc) - timedelta(days=2)
        request.events = [
            {**e, "at": earlier.isoformat()} if e["kind"] == "contract_signed" else e
            for e in request.events
        ]
        await db.commit()

    _FakeValidator.report = _report((f"CN={partner}", "TOTAL_PASSED", "QESig"))
    nda_signed = NDA + b"% podpis kontraktora\n"
    done_nda = await app_client.post(
        f"/api/public/b2b-sign/{token}/documents/{document['id']}",
        files={"file": ("n.pdf", nda_signed, "application/pdf")},
    )
    assert done_nda.status_code == 200, done_nda.text
    assert done_nda.json()["status"] == "signed_by_you"
    assert done_nda.json()["documents"][0]["signed"] is True

    async with AsyncSessionLocal() as db:
        pair = await db.scalar(
            select(PlacementStartDocument).where(
                PlacementStartDocument.document_id == nda_id,
                PlacementStartDocument.candidate_id == scenario["candidate_id"],
                PlacementStartDocument.job_id == scenario["job_id"],
            )
        )
        assert pair is not None and pair.status == "delivered"
        assert pair.file_name == "NDA klienta (podpis w NEXUSIE).pdf"
        assert storage_service.read_start_document_file(pair.file_path) == nda_signed
        admin_name = (await db.get(User, admin_id)).name

    mine = await app_client.get(
        "/api/b2b-generator/esign/mine", headers=app_auth_headers
    )
    assert request_id in [r["id"] for r in mine.json()]
    _FakeValidator.report = _report(
        (f"CN={partner}", "TOTAL_PASSED", "QESig"),
        (f"CN={admin_name}", "TOTAL_PASSED", "QESig"),
    )
    company = await app_client.post(
        f"/api/b2b-generator/esign/{request_id}/company-sign",
        files={"file": ("u.pdf", contract_pdf + b"% firma\n", "application/pdf")},
        headers=app_auth_headers,
    )
    assert company.status_code == 200, company.text
    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, scenario["generated_id"])
        request = await db.get(B2BSigningRequest, request_id)
        assert row.signature_status == "signed_both"
        assert row.signed_on == business_date(service.contract_signed_at(request))
        assert row.signed_on < business_date(request.contractor_signed_at)


@pytest.mark.asyncio
async def test_sender_can_leave_documents_out_but_not_add_foreign_ones(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    esign_env,  # noqa: F811
):
    admin_id = esign_env["admin_id"]
    await _use_admin_as_company_signer(admin_id)
    scenario = await _seed_in_progress(created_by=admin_id)
    await _client_template(scenario["client_id"], "NDA klienta", NDA)

    foreign = await _send(
        app_client,
        app_auth_headers,
        scenario["generated_id"],
        admin_id,
        start_document_ids=[987654],
    )
    assert foreign.status_code == 422, foreign.text

    without = await _send(
        app_client,
        app_auth_headers,
        scenario["generated_id"],
        admin_id,
        start_document_ids=[],
    )
    assert without.status_code == 200, without.text
    assert without.json()["request"]["documents"] == []
    token = _token(without.json()["sign_url"])
    partner = await _partner(scenario["generated_id"])
    _FakeValidator.report = _report((f"CN={partner}", "TOTAL_PASSED", "QESig"))
    signed = await app_client.post(
        f"/api/public/b2b-sign/{token}",
        files={"file": ("u.pdf", SOURCE + b"% podpis\n", "application/pdf")},
    )
    # Bez dokumentów umowa idzie do firmy od razu, jak dotąd.
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "signed_by_you"
