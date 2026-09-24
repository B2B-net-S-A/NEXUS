"""„Powiąż z kontraktem” dla podpisanej umowy bez kontraktora (ticket 1460/2026).

Znacznik „Kontrakt usunięty — brak kontraktora” nie miał wyjścia w interfejsie:
umowa została wygenerowana dla zdublowanego rekordu osoby i złego klienta,
kontrakt założony przy podpisie usunięto, a właściwy kontrakt istniał osobno.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api import b2b_contract_generator
from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.b2b_generated_contract import B2BGeneratedContract
from app.models.b2b_generated_contract_status_event import (
    B2BGeneratedContractStatusEvent,
)
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.contract_document import ContractDocument

pytestmark = pytest.mark.asyncio

PATH = "/api/b2b-generator/generated"


async def _seed(*, signature_status: str = "signed_both", status: str = "active"):
    suffix = uuid.uuid4().hex[:8]
    seq = 100000 + (uuid.uuid4().int % 800000)
    async with AsyncSessionLocal() as db:
        wrong_client = Client(name=f"Link wrong client {suffix}")
        right_client = Client(name=f"Link right client {suffix}")
        dup = Candidate(name="Agnieszka", lastname=f"Link{suffix}")
        person = Candidate(name="Agnieszka", lastname=f"Link{suffix}")
        db.add_all([wrong_client, right_client, dup, person])
        await db.flush()
        contract = Contract(
            candidate_id=person.id,
            client_id=right_client.id,
            start_date=date(2026, 8, 17),
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.flush()
        row = B2BGeneratedContract(
            year=2026,
            seq=seq,
            contract_number=f"{seq}/2026",
            partner_name="Agnieszka Link",
            client_name="Right Client",
            language="pl",
            candidate_id=dup.id,
            client_id=wrong_client.id,
            contract_id=None,
            signature_status=signature_status,
            contract_status=status,
            # payload bez danych formularza — render się nie uda, operacja
            # ma i tak powiązać umowę i powiedzieć, że plik trzeba dołączyć
            render_payload={"language": "pl"},
        )
        db.add(row)
        await db.commit()
        return {
            "row": row.id,
            "number": row.contract_number,
            "contract": contract.id,
            "person": person.id,
            "dup": dup.id,
            "right_client": right_client.id,
            "wrong_client": wrong_client.id,
        }


async def _render_fails(db, row):
    raise HTTPException(status_code=422, detail="brak danych formularza")


async def test_link_sets_contract_aligns_person_and_logs_history(
    app_client, app_auth_headers, monkeypatch
):
    monkeypatch.setattr(
        b2b_contract_generator, "_render_generated_row_docx", _render_fails
    )
    ids = await _seed()
    resp = await app_client.post(
        f"{PATH}/{ids['row']}/link-contract",
        json={"contract_id": ids["contract"]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["item"]["contract_id"] == ids["contract"]
    assert body["document_attached"] is False
    assert body["document_note"]

    async with AsyncSessionLocal() as db:
        row = await db.get(B2BGeneratedContract, ids["row"])
        assert row.contract_id == ids["contract"]
        assert row.candidate_id == ids["person"]
        assert row.client_id == ids["right_client"]
        # numer, statusy i podpis bez zmian
        assert row.contract_number == ids["number"]
        assert row.contract_status == "active"
        assert row.signature_status == "signed_both"
        event = await db.scalar(
            select(B2BGeneratedContractStatusEvent).where(
                B2BGeneratedContractStatusEvent.generated_contract_id == ids["row"]
            )
        )
        assert event is not None
        assert event.from_status == event.to_status == "active"
        assert event.details["source"] == "linked_to_contract"
        assert event.details["contract_id"] == ids["contract"]
        assert event.details["previous_candidate_id"] == ids["dup"]
        assert event.details["previous_client_id"] == ids["wrong_client"]
        activity = await db.scalar(
            select(Activity).where(
                Activity.entity_type == "contract",
                Activity.entity_id == ids["contract"],
                Activity.action == "generated_contract_linked",
            )
        )
        assert activity is not None


async def test_link_attaches_the_rendered_agreement_to_contract_documents(
    app_client, app_auth_headers, monkeypatch
):
    async def render_ok(db, row):
        return b"PK-docx"

    monkeypatch.setattr(
        b2b_contract_generator, "_render_generated_row_docx", render_ok
    )
    monkeypatch.setattr(
        "app.services.storage_service.save_contract_document",
        lambda contract_id, filename, fileobj, stored_name=None: (
            f"contracts/{contract_id}/{stored_name}",
            7,
        ),
    )
    ids = await _seed()
    resp = await app_client.post(
        f"{PATH}/{ids['row']}/link-contract",
        json={"contract_id": ids["contract"]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["document_attached"] is True
    async with AsyncSessionLocal() as db:
        docs = list(
            (
                await db.scalars(
                    select(ContractDocument).where(
                        ContractDocument.contract_id == ids["contract"]
                    )
                )
            ).all()
        )
    assert [d.filename for d in docs] == [
        f"Umowa {ids['number'].replace('/', '-')}.docx"
    ]


async def test_link_refuses_unsigned_agreement(app_client, app_auth_headers):
    ids = await _seed(signature_status="unsigned", status="in_progress")
    resp = await app_client.post(
        f"{PATH}/{ids['row']}/link-contract",
        json={"contract_id": ids["contract"]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text


async def test_link_refuses_when_contract_already_has_an_agreement(
    app_client, app_auth_headers
):
    ids = await _seed()
    first = await app_client.post(
        f"{PATH}/{ids['row']}/link-contract",
        json={"contract_id": ids["contract"]},
        headers=app_auth_headers,
    )
    assert first.status_code == 200, first.text
    other = await _seed()
    resp = await app_client.post(
        f"{PATH}/{other['row']}/link-contract",
        json={"contract_id": ids["contract"]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert ids["number"] in resp.json()["detail"]


async def test_link_refuses_agreement_with_a_live_contract(
    app_client, app_auth_headers
):
    ids = await _seed()
    await app_client.post(
        f"{PATH}/{ids['row']}/link-contract",
        json={"contract_id": ids["contract"]},
        headers=app_auth_headers,
    )
    other = await _seed()
    resp = await app_client.post(
        f"{PATH}/{ids['row']}/link-contract",
        json={"contract_id": other["contract"]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
