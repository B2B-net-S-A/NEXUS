"""Dokumenty pochodne umowy B2B — API i skutki podpisu.

Render szablonów jest tu podmieniony (szablony mają osobny test
``test_b2b_document_templates.py``) — ten plik sprawdza zapis, bramki,
dane wrażliwe i to, co „Oznacz jako podpisany” zmienia w kontraktach.

Baza wspólna i nieczyszczona — asercje wyłącznie na własnych wierszach.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.services.b2b_documents.contract_versions import default_refs, notice_end_date
from app.services.b2b_documents.registry import TYPES, missing_required, strip_sensitive
from tests.test_b2b_generated_contract_status import (
    _admin_user_id,
    _link,
    _seed,
    _seed_linked_contract,
)
from tests.test_b2b_generator_rate_visibility import _seed_user

BASE = "/api/b2b-generator"


@pytest.fixture(autouse=True)
def _fake_render(monkeypatch):
    from app.api import b2b_documents

    monkeypatch.setattr(
        b2b_documents, "render_docx", lambda key, ctx: b"PK-" + key.encode()
    )
    monkeypatch.setattr(b2b_documents, "render_html", lambda key, ctx: f"<p>{key}</p>")


async def _signed_parent(app_client) -> tuple[int, int]:
    """Podpisana umowa w rejestrze powiązana z aktywnym kontraktem."""
    admin_id = await _admin_user_id(app_client)
    rid, _number = await _seed(admin_id, signature_status="signed_both")
    contract_id, client_id = await _seed_linked_contract()
    await _link(rid, contract_id=contract_id)
    from app.models.b2b_generated_contract import B2BGeneratedContract

    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, rid)
        row.client_id = client_id
        row.template_version = "2026"
        await db.commit()
    return rid, contract_id


def _values(**extra) -> dict:
    return {
        "document_date": "2026-09-23",
        "gender": "k",
        "partner_name": "Anna Testowa",
        "partner_legal_name": "Anna Testowa IT",
        **extra,
    }


async def _create(app_client, headers, doc_type: str, parent_id: int | None, **values):
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=headers,
        json={
            "document_type": doc_type,
            "language": "pl",
            "parent_generated_contract_id": parent_id,
            "values": _values(**values),
        },
    )
    assert resp.status_code == 200, resp.text
    return int(resp.headers["X-Document-Id"])


# ── czyste reguły ────────────────────────────────────────────────────────────


def test_every_type_declares_fields_and_languages():
    assert len(TYPES) == 10
    for doc_type in TYPES.values():
        assert doc_type.languages
        assert any(f.key == "document_date" for f in doc_type.fields)


def test_sensitive_fields_are_stripped_before_storage():
    doc_type = TYPES["preliminary_cez"]
    stored = strip_sensitive(
        doc_type, {"pesel": "90010112345", "id_document": "ABC", "project_number": "7"}
    )
    assert stored == {"project_number": "7"}


def test_required_fields_respect_show_if():
    doc_type = TYPES["termination_agreement"]
    base = {
        "document_date": "2026-09-23",
        "gender": "m",
        "partner_name": "X",
        "termination_date": "2026-09-30",
        "last_service_date": "2026-09-30",
    }
    assert missing_required(doc_type, {**base, "release_non_compete": False}) == []
    assert missing_required(doc_type, {**base, "release_non_compete": True}) == [
        "Klient, którego dotyczy zwolnienie"
    ]


@pytest.mark.parametrize(
    ("delivered", "expected"),
    [
        (date(2026, 9, 15), date(2026, 10, 31)),
        (date(2026, 9, 1), date(2026, 10, 31)),
        (date(2026, 12, 10), date(2027, 1, 31)),
        (date(2026, 1, 31), date(2026, 2, 28)),
    ],
)
def test_notice_end_date_is_end_of_following_month(delivered, expected):
    assert notice_end_date(delivered, default_refs()) == expected


# ── API ──────────────────────────────────────────────────────────────────────


async def test_document_types_endpoint(app_client, app_auth_headers):
    resp = await app_client.get(f"{BASE}/document-types", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {t["key"] for t in body["types"]} == set(TYPES)
    assert body["ref_defaults"]["non_compete_paragraph"] == "§ 10 ust. 1"


async def test_prefill_uses_the_base_contract(app_client, app_auth_headers):
    rid, _ = await _signed_parent(app_client)
    resp = await app_client.get(
        f"{BASE}/documents/prefill",
        headers=app_auth_headers,
        params={
            "document_type": "termination_notice",
            "parent_generated_contract_id": rid,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["values"]["partner_name"] == "Jan Kowalski"
    assert body["needs_refs"] is False
    # Wypowiedzenie: data rozwiązania wyliczona z okresu wypowiedzenia.
    assert body["values"]["termination_date"] > body["values"]["delivery_date"]


async def test_missing_fields_are_422_with_labels(app_client, app_auth_headers):
    rid, _ = await _signed_parent(app_client)
    resp = await app_client.post(
        f"{BASE}/documents",
        headers=app_auth_headers,
        json={
            "document_type": "termination_agreement",
            "parent_generated_contract_id": rid,
            "values": {"document_date": "2026-09-23", "gender": "m"},
        },
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "document_fields_missing"
    assert "Umowa ulega rozwiązaniu z dniem" in detail["missing"]


async def test_generating_changes_nothing_and_signing_terminates(
    app_client, app_auth_headers
):
    """Generowanie nie rusza kontraktu — robi to dopiero „Oznacz jako podpisany”."""
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.contract import Contract, ContractTerminationReason

    rid, contract_id = await _signed_parent(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "termination_agreement",
        rid,
        termination_date="2026-10-31",
        last_service_date="2026-10-31",
    )
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.terminated_at is None

    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=app_auth_headers
    )
    assert effects.status_code == 200, effects.text
    assert effects.json()["blockers"] == []
    assert any("31.10.2026" in c for c in effects.json()["changes"])

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    assert signed.json()["signature_status"] == "signed_both"

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.terminated_at == date(2026, 10, 31)
        assert contract.termination_reason == ContractTerminationReason.mutual_agreement
        row = await db.get(B2BGeneratedContract, rid)
        if date(2026, 10, 31) >= business_today():
            # Umowa obowiązuje do daty rozwiązania — zamknie ją nocny cron po
            # zakończeniu kontraktu (audyt 25.09.2026, runda 3). Dokument
            # zostawia na wierszu tylko tryb rozwiązania.
            assert row.contract_status == "active"
            assert row.closure_date is None
        else:
            assert row.contract_status == "closed"
            assert row.closure_date == date(2026, 10, 31)
        assert row.termination_mode == "mutual_agreement"

    again = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert again.status_code == 200, again.text


async def test_rate_annex_goes_through_the_amendment_path(app_client, app_auth_headers):
    from app.models.contract import Contract, RateUnit
    from app.models.contract_amendment import ContractAmendment, ContractAmendmentType

    rid, contract_id = await _signed_parent(app_client)
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        contract.rate_candidate = Decimal("150")
        contract.rate_candidate_currency = "PLN"
        contract.rate_unit = RateUnit.hourly
        await db.commit()
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        rid,
        effective_date="2026-11-01",
        new_rate="165",
        currency="PLN",
    )
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        amendment = await db.scalar(
            select(ContractAmendment).where(
                ContractAmendment.contract_id == contract_id,
                ContractAmendment.amendment_type == ContractAmendmentType.rate_change,
            )
        )
        assert amendment is not None
        assert amendment.document_id is not None
        assert Decimal(str(amendment.new_values["rate_candidate"])) == Decimal("165")


async def test_withdrawal_reopens_the_register_and_leaves_the_contract_to_reversal(
    app_client, app_auth_headers
):
    """Cofnięcie wypowiedzenia wraca umowę w rejestrze na „Aktywną”, ale
    kontraktu samo nie przywraca — wyczyszczenie dat zostawiłoby skrócone
    zamówienia; pełne cofnięcie robi „Cofnij zakończenie” w Kontraktach."""
    from app.models.b2b_generated_contract import B2BGeneratedContract
    from app.models.contract import Contract

    rid, contract_id = await _signed_parent(app_client)
    notice = await app_client.post(
        f"{BASE}/documents/partner-notice",
        headers=app_auth_headers,
        json={"parent_generated_contract_id": rid, "delivered_on": "2026-09-15"},
    )
    assert notice.status_code == 200, notice.text
    assert notice.json()["termination_date"] == "2026-10-31"

    doc_id = await _create(
        app_client,
        app_auth_headers,
        "notice_withdrawal",
        rid,
        notice_delivery_date="2026-09-15",
    )
    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=app_auth_headers
    )
    assert any("Cofnij zakończenie" in w for w in effects.json()["warnings"])
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.terminated_at == date(2026, 10, 31)
        row = await db.get(B2BGeneratedContract, rid)
        assert row.contract_status == "active"
        assert row.closure_date is None


async def test_sensitive_values_never_reach_the_database(app_client, app_auth_headers):
    from app.api import b2b_documents
    from app.models.b2b_contract_document import B2BContractDocument

    rid, _ = await _signed_parent(app_client)
    pesel = "90010112345"
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_party_data",
        rid,
        partner_home_address="ul. Tajna 1, Warszawa",
        id_document="ABC123456",
        entity_type="sole_trader",
        new_legal_name="Anna Testowa IT",
        new_business_address="ul. Firmowa 2, Warszawa",
        new_nip="5270103391",
        new_regon="012345678",
        effective_date="2026-10-01",
        pesel=pesel,
    )
    async with AsyncSessionLocal() as db:
        doc = await db.get(B2BContractDocument, doc_id)
        dumped = str(doc.render_payload)
    assert "Tajna" not in dumped
    assert "ABC123456" not in dumped
    assert b2b_documents is not None

    no_values = await app_client.post(
        f"{BASE}/documents/{doc_id}/docx", headers=app_auth_headers, json={"values": {}}
    )
    assert no_values.status_code == 422, no_values.text
    assert no_values.json()["detail"]["code"] == "sensitive_values_required"
    with_values = await app_client.post(
        f"{BASE}/documents/{doc_id}/docx",
        headers=app_auth_headers,
        json={"values": {"partner_home_address": "ul. Tajna 1, Warszawa"}},
    )
    assert with_values.status_code == 200, with_values.text


async def test_signing_without_sensitive_values_does_not_archive_an_empty_file(
    app_client, app_auth_headers
):
    """PESEL/adres nie są przechowywane — plik z pustymi polami nie może
    trafić do dokumentów kontraktu jako „podpisany”."""
    from app.models.b2b_contract_document import B2BContractDocument

    rid, _ = await _signed_parent(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_party_data",
        rid,
        partner_home_address="ul. Tajna 1, Warszawa",
        id_document="ABC123456",
        entity_type="sole_trader",
        new_legal_name="Anna Testowa IT",
        new_business_address="ul. Firmowa 2, Warszawa",
        new_nip="5270103391",
        new_regon="012345678",
        effective_date="2026-10-01",
    )
    effects = await app_client.get(
        f"{BASE}/documents/{doc_id}/effects", headers=app_auth_headers
    )
    assert any("nie przechowuje" in w for w in effects.json()["warnings"])
    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    async with AsyncSessionLocal() as db:
        doc = await db.get(B2BContractDocument, doc_id)
        assert doc.effect_summary.get("docx_not_archived") is True
        assert "contract_document_id" not in doc.effect_summary
        assert "Tajna" not in str(doc.effect_summary)


async def test_signature_permission_alone_does_not_terminate_a_contract(
    app_client, app_auth_headers
):
    """TAC/TCM mają „Oznaczanie podpisu”, ale nie trasy /terminate — podpis
    dokumentu nie może być bocznymi drzwiami do zmian w kontrakcie."""
    from app.models.contract import Contract

    rid, contract_id = await _signed_parent(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "termination_agreement",
        rid,
        termination_date="2026-10-31",
        last_service_date="2026-10-31",
    )
    tac_headers, _ = await _seed_user(app_client, "tac")
    resp = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=tac_headers
    )
    assert resp.status_code in (403, 409), resp.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract.terminated_at is None


async def test_rate_annex_is_hidden_from_someone_who_cannot_see_the_rate(
    app_client, app_auth_headers
):
    rid, _ = await _signed_parent(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_rate_change",
        rid,
        effective_date="2026-11-01",
        new_rate="165",
        currency="PLN",
    )
    recruiter_headers, _ = await _seed_user(app_client, "recruiter")
    for path in (f"/documents/{doc_id}/effects", f"/documents/{doc_id}/form"):
        resp = await app_client.get(f"{BASE}{path}", headers=recruiter_headers)
        assert resp.status_code == 403, (path, resp.text)


async def test_prefill_by_candidate_requires_a_recruitment(
    app_client, app_auth_headers
):
    """Bez rekrutacji `candidate_id` byłby wyliczanką NIP-ów całej bazy."""
    resp = await app_client.get(
        f"{BASE}/documents/prefill",
        headers=app_auth_headers,
        params={"document_type": "preliminary_cez", "candidate_id": 1},
    )
    assert resp.status_code == 422, resp.text


async def test_signed_document_is_frozen_and_foreign_edit_is_403(
    app_client, app_auth_headers
):
    rid, _ = await _signed_parent(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-01",
        new_start_date_mode="exact",
    )
    other_h, _ = await _seed_user(app_client, "tac")
    foreign = await app_client.delete(f"{BASE}/documents/{doc_id}", headers=other_h)
    assert foreign.status_code in (403, 404), foreign.text

    signed = await app_client.post(
        f"{BASE}/documents/{doc_id}/confirm-signed", headers=app_auth_headers
    )
    assert signed.status_code == 200, signed.text
    rerender = await app_client.post(
        f"{BASE}/documents/{doc_id}/rerender",
        headers=app_auth_headers,
        json={
            "document_type": "annex_start_date",
            "parent_generated_contract_id": rid,
            "values": _values(new_start_date="2026-12-01", new_start_date_mode="exact"),
        },
    )
    assert rerender.status_code == 409, rerender.text


async def test_documents_list_filters_by_parent(app_client, app_auth_headers):
    rid, _ = await _signed_parent(app_client)
    doc_id = await _create(
        app_client,
        app_auth_headers,
        "annex_start_date",
        rid,
        new_start_date="2026-11-01",
        new_start_date_mode="exact",
    )
    resp = await app_client.get(
        f"{BASE}/documents",
        headers=app_auth_headers,
        params={"parent_generated_contract_id": rid},
    )
    assert resp.status_code == 200, resp.text
    [item] = resp.json()
    assert item["id"] == doc_id
    assert item["label"].startswith("Aneks — zmiana daty rozpoczęcia z dnia 23.09.2026")
    assert item["can_edit"] is True


async def test_preliminary_requires_a_cez_recruitment(
    app_client, app_auth_headers, monkeypatch
):
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services import ezdrowie

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"CeZ test {unique}")
        cand = Candidate(
            name="Ewa", lastname=f"P-{unique}", email=f"p-{unique}@example.com"
        )
        db.add_all([client, cand])
        await db.flush()
        job = Job(title="Analityk", client_id=client.id, status=JobStatus.published)
        db.add(job)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id, job_id=job.id, stage=PipelineStage.verified
            )
        )
        await db.commit()
        client_id, cand_id, job_id = client.id, cand.id, job.id

    body = {
        "document_type": "preliminary_cez",
        "candidate_id": cand_id,
        "job_id": job_id,
        "values": {
            "document_date": "2026-09-23",
            "gender": "k",
            "partner_name": "Ewa P",
            "partner_home_address": "ul. Domowa 3",
            "id_document": "XYZ000111",
            "pesel": "91020212345",
            "project_number": "CeZ/1/2026",
            "hourly_rate": "140",
            "valid_until": "2026-11-22",
        },
    }
    wrong = await app_client.post(
        f"{BASE}/documents", headers=app_auth_headers, json=body
    )
    assert wrong.status_code == 422, wrong.text

    monkeypatch.setattr(ezdrowie, "EZDROWIE_CLIENT_ID", client_id)
    ok = await app_client.post(f"{BASE}/documents", headers=app_auth_headers, json=body)
    assert ok.status_code == 200, ok.text
    from app.models.b2b_contract_document import B2BContractDocument

    async with AsyncSessionLocal() as db:
        doc = await db.get(B2BContractDocument, int(ok.headers["X-Document-Id"]))
        assert "91020212345" not in str(doc.render_payload)
        assert doc.parent_generated_contract_id is None
        assert doc.client_id == client_id
