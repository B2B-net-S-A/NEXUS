"""Dane firm z umów (0755): wybór pliku, odczyt, lista, „Zastosuj”, „Odrzuć”, rejestr.

Model i rejestr są podmienione (bez wywołań na zewnątrz). Baza wspólna
i nieczyszczona: asercje wyłącznie na własnych wierszach. Dane zmyślone,
numery NIP i REGON liczone z fikcyjnych prefiksów.
"""

from __future__ import annotations

import json
import random
import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.contract_partner_read import ContractPartnerRead
from app.services import storage_service
from app.services.b2b_contract_generator import registry_verification
from app.services.contract_partner_reads import reader, service
from tests.test_contract_partner_reads_reader import valid_nip, valid_regon

URL = "/api/contract-partner-reads"


async def _contract(**candidate_fields) -> tuple[int, int]:
    """Aktywny kontrakt B2B z kandydatem: ``(contract_id, candidate_id)``."""

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Partnerka",
            lastname=f"Testowa-{suffix}",
            email=candidate_fields.pop("email", f"partner-{suffix}@example.com"),
            **candidate_fields,
        )
        client = Client(name=f"Klient Testowy {suffix}")
        db.add_all([candidate, client])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            contract_type=ContractType.b2b,
        )
        db.add(contract)
        await db.commit()
        return contract.id, candidate.id


async def _document(
    contract_id: int,
    filename: str = "Umowa 7-2026 podpisana.pdf",
    doc_type: ContractDocumentType = ContractDocumentType.contract,
) -> int:
    async with AsyncSessionLocal() as db:
        doc = ContractDocument(
            contract_id=contract_id,
            filename=filename,
            file_path=f"contracts/{contract_id}/{uuid.uuid4().hex}.pdf",
            content_type=reader.mime_for(filename, None),
            doc_type=doc_type,
        )
        db.add(doc)
        await db.commit()
        return doc.id


def _fields(**over) -> dict:
    base = {
        "gender": "k",
        "partner_name": "Anna Testowa",
        "partner_legal_name": "Testowa Consulting Anna Testowa",
        "partner_entity_type": "sole_trader",
        "partner_nip": valid_nip(),
        "partner_regon": valid_regon(),
        "partner_business_address": "ul. Przykładowa 1, 00-001 Testowo",
        "partner_email": "biuro-testowa@example.com",
        "partner_phone": "+48 600 000 000",
    }
    base.update(over)
    return {
        name: {"value": base.get(name), "quote": None, "quote_found": None}
        for name in reader.FIELDS
    }


async def _read(
    contract_id: int, document_id: int, *, status: str = "read", **over
) -> int:
    async with AsyncSessionLocal() as db:
        row = ContractPartnerRead(
            contract_document_id=document_id,
            contract_id=contract_id,
            reader_version=reader.READER_VERSION,
            status=status,
            result={
                "version": reader.READER_VERSION,
                "status": status,
                "mode": "text",
                "document_kind": "contract",
                "agreement_number": "7/2026",
                "fields": _fields(**over) if status == "read" else {},
                "issues": [],
            },
        )
        db.add(row)
        await db.commit()
        return row.id


async def _candidate(candidate_id: int) -> Candidate:
    async with AsyncSessionLocal() as db:
        return await db.get(Candidate, candidate_id)


async def test_scan_picks_main_contract_file_and_skips_generator_data():
    contract_id, candidate_id = await _contract()
    main = await _document(contract_id, "Umowa 7-2026 podpisana.pdf")
    await _document(contract_id, "Umowa 7-2026.docx")
    await _document(
        contract_id, "Aneks 1 do umowy 7-2026.pdf", ContractDocumentType.annex
    )
    covered_id, covered_candidate = await _contract()
    covered_doc = await _document(covered_id)
    seq = random.randint(10_000_000, 99_999_999)
    async with AsyncSessionLocal() as db:
        db.add(
            B2BGeneratedContract(
                year=2031,
                seq=seq,
                contract_number=f"{seq}/2031",
                partner_name="Osoba Testowa",
                language="pl",
                signature_status="unsigned",
                contract_status="in_progress",
                candidate_id=covered_candidate,
                render_payload={"partner_nip": valid_nip()},
            )
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        pending = {d.id for d in (await service.scan(db)).pending}
    assert main in pending
    assert covered_doc not in pending


async def test_read_row_with_fake_model_lands_on_the_open_list(
    app_client, app_auth_headers, monkeypatch, tmp_path
):
    contract_id, _ = await _contract()
    document_id = await _document(contract_id)
    stored = tmp_path / "umowa.pdf"
    stored.write_bytes(b"\xff\xd8fake")
    monkeypatch.setattr(
        storage_service, "get_contract_document_path", lambda _p: stored
    )
    reply = {
        "document_kind": "contract",
        "fields": {"partner_nip": {"value": valid_nip(), "quote": "NIP"}},
    }
    monkeypatch.setattr(reader, "_call_model", lambda _blocks: json.dumps(reply))

    async with AsyncSessionLocal() as db:
        docs = [d for d in (await service.scan(db)).pending if d.id == document_id]
        row = await service.read_document_row(db, docs[0])
        await db.commit()
    assert row.status == "read"

    resp = await app_client.get(f"{URL}?state=open&limit=100", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    item = next(i for i in body["items"] if i["id"] == row.id)
    nip = next(f for f in item["fields"] if f["name"] == "partner_nip")
    assert nip["value"] == valid_nip() and nip["column"] == "nip"
    assert {"open", "to_read", "without_file"} <= set(body["counts"])
    async with AsyncSessionLocal() as db:
        assert document_id not in {d.id for d in (await service.scan(db)).pending}


async def test_apply_writes_only_empty_candidate_columns(app_client, app_auth_headers):
    contract_id, candidate_id = await _contract(legal_name="Stara Firma Testowa")
    read_id = await _read(contract_id, await _document(contract_id))

    resp = await app_client.post(
        f"{URL}/{read_id}/apply", json={}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["decision"] == "applied"
    assert body["candidate_changes"]["legal_name"] == {"action": "kept"}
    assert body["candidate_changes"]["email"] == {"action": "kept"}
    assert body["confirmed"]["fields"]["partner_legal_name"] == (
        "Testowa Consulting Anna Testowa"
    )
    candidate = await _candidate(candidate_id)
    assert candidate.legal_name == "Stara Firma Testowa"
    assert candidate.nip == valid_nip()
    assert candidate.regon == valid_regon()
    assert candidate.phone == "+48 600 000 000"
    assert candidate.email.startswith("partner-")

    again = await app_client.post(
        f"{URL}/{read_id}/apply", json={}, headers=app_auth_headers
    )
    assert again.status_code == 409


async def test_apply_with_overwrite_and_correction(app_client, app_auth_headers):
    contract_id, candidate_id = await _contract(
        legal_name="Stara Firma Testowa", business_address="stary adres"
    )
    read_id = await _read(contract_id, await _document(contract_id), partner_regon=None)
    resp = await app_client.post(
        f"{URL}/{read_id}/apply",
        json={"overwrite": True, "values": {"partner_regon": valid_regon()}},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["confirmed"]["corrected"] == ["partner_regon"]
    candidate = await _candidate(candidate_id)
    assert candidate.legal_name == "Testowa Consulting Anna Testowa"
    assert candidate.business_address == "ul. Przykładowa 1, 00-001 Testowo"
    assert candidate.regon == valid_regon()


async def test_bad_correction_is_refused_and_nothing_changes(
    app_client, app_auth_headers
):
    contract_id, candidate_id = await _contract()
    read_id = await _read(contract_id, await _document(contract_id))
    resp = await app_client.post(
        f"{URL}/{read_id}/apply",
        json={"values": {"partner_nip": "1234567890"}},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert (await _candidate(candidate_id)).nip is None
    async with AsyncSessionLocal() as db:
        assert (await db.get(ContractPartnerRead, read_id)).decision is None


async def test_dismiss_moves_read_off_the_open_list(app_client, app_auth_headers):
    contract_id, candidate_id = await _contract()
    read_id = await _read(contract_id, await _document(contract_id))
    resp = await app_client.post(f"{URL}/{read_id}/dismiss", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision"] == "dismissed"
    assert (await _candidate(candidate_id)).nip is None
    dismissed = await app_client.get(
        f"{URL}?state=dismissed&limit=100", headers=app_auth_headers
    )
    assert read_id in {i["id"] for i in dismissed.json()["items"]}
    apply = await app_client.post(
        f"{URL}/{read_id}/apply", json={}, headers=app_auth_headers
    )
    assert apply.status_code == 409


async def test_failed_read_cannot_be_applied(app_client, app_auth_headers):
    contract_id, _ = await _contract()
    read_id = await _read(contract_id, await _document(contract_id), status="failed")
    resp = await app_client.post(
        f"{URL}/{read_id}/apply", json={}, headers=app_auth_headers
    )
    assert resp.status_code == 409
    failed = await app_client.get(
        f"{URL}?state=failed&limit=100", headers=app_auth_headers
    )
    assert read_id in {i["id"] for i in failed.json()["items"]}


async def test_verify_asks_the_registry_once_and_compares(
    app_client, app_auth_headers, monkeypatch
):
    contract_id, _ = await _contract()
    read_id = await _read(contract_id, await _document(contract_id))
    calls: list[tuple] = []

    async def fake_verify(nip=None, krs=None):
        calls.append((nip, krs))
        return {
            "status": "verified",
            "registry": "ceidg",
            "checked_at": "2026-11-22T10:00:00+00:00",
            "company": {
                "name": "TESTOWA CONSULTING ANNA TESTOWA",
                "nip": nip,
                "address": "ul. Przykładowa 2, 00-001 Testowo",
            },
            "warnings": [],
            "message": None,
        }

    monkeypatch.setattr(registry_verification, "verify_company", fake_verify)
    resp = await app_client.post(
        f"{URL}/{read_id}/verify", json={}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    comparison = {c["field"]: c for c in resp.json()["verification"]["comparison"]}
    assert comparison["partner_legal_name"]["same"] is True
    assert comparison["partner_business_address"]["same"] is False
    again = await app_client.post(
        f"{URL}/{read_id}/verify", json={}, headers=app_auth_headers
    )
    assert again.status_code == 200
    assert calls == [(valid_nip(), None)]


async def test_unknown_read_is_404(app_client, app_auth_headers):
    async with AsyncSessionLocal() as db:
        top = await db.scalar(
            select(ContractPartnerRead.id).order_by(ContractPartnerRead.id.desc())
        )
    resp = await app_client.post(
        f"{URL}/{(top or 0) + 10_000}/dismiss", headers=app_auth_headers
    )
    assert resp.status_code == 404
