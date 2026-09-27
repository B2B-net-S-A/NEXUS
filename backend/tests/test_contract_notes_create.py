"""Runda 10 (F03): notatkę dodaje się bezpośrednio przy kontrakcie.

Do 26.09.2026 pusta zakładka „Notatki / Rozmowy" kontraktu kazała „ustawić
contract_id" albo dodać notatkę z kandydata, a formularz kandydata nie ma
wyboru kontraktu. `POST /api/contracts/{id}/notes` zapisuje notatkę z
`contract_id` i `candidate_id` kontraktu — widać ją w obu widokach.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import AsyncIterator

import pytest_asyncio
from httpx import AsyncClient

from app.core.scheduling import business_today


@pytest_asyncio.fixture
async def note_contract() -> AsyncIterator[dict]:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType
    from app.models.note import Note

    token = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="ContractNote",
            lastname=f"Owned-{token}",
            email=f"cnote-{token}@example.com",
        )
        client = Client(name=f"ContractNote {token}")
        db.add_all([cand, client])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            contract_type=ContractType("b2b"),
            start_date=business_today() - timedelta(days=30),
            rate_client=100,
            rate_candidate=80,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        ids = {"id": contract.id, "candidate_id": cand.id, "client_id": client.id}

    try:
        yield ids
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(Note).where(Note.candidate_id == ids["candidate_id"])
            )
            await db.execute(
                delete(Activity).where(
                    Activity.entity_type == "contract",
                    Activity.entity_id == ids["id"],
                )
            )
            await db.execute(delete(Contract).where(Contract.id == ids["id"]))
            await db.execute(
                delete(Candidate).where(Candidate.id == ids["candidate_id"])
            )
            await db.execute(delete(Client).where(Client.id == ids["client_id"]))
            await db.commit()


async def test_note_added_on_contract_shows_on_contract_and_candidate(
    app_client: AsyncClient, app_auth_headers: dict, note_contract: dict
):
    cid = note_contract["id"]
    created = await app_client.post(
        f"/api/contracts/{cid}/notes",
        json={"content": "  Rozmowa o przedłużeniu  ", "note_type": "call"},
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "note"
    assert body["content"] == "Rozmowa o przedłużeniu"
    assert body["sub_type"] == "call"

    timeline = await app_client.get(
        f"/api/contracts/{cid}/notes", headers=app_auth_headers
    )
    assert timeline.status_code == 200
    assert [i["id"] for i in timeline.json() if i["kind"] == "note"] == [body["id"]]

    candidate_notes = await app_client.get(
        f"/api/notes?candidate_id={note_contract['candidate_id']}",
        headers=app_auth_headers,
    )
    assert candidate_notes.status_code == 200
    assert body["id"] in [n["id"] for n in candidate_notes.json()["items"]]


async def test_blank_contract_note_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict, note_contract: dict
):
    res = await app_client.post(
        f"/api/contracts/{note_contract['id']}/notes",
        json={"content": "   "},
        headers=app_auth_headers,
    )
    assert res.status_code == 422


async def test_note_on_missing_contract_is_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    res = await app_client.post(
        "/api/contracts/999999999/notes",
        json={"content": "x"},
        headers=app_auth_headers,
    )
    assert res.status_code == 404
