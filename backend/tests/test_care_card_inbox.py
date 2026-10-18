"""„Karty do połączenia” (``/api/care/clients/{id}/tech-cards/unlinked``,
``/api/care/tech-cards/{id}/link``) — testy na bazie.

Karta z importu Compassa bez kontraktu czeka przy kliencie; lista podaje
propozycje (kontrakty tej osoby u klienta), a „Połącz” zapisuje kontrakt
tylko tego samego klienta i tylko na karcie jeszcze bez kontraktu.
Dane zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.contract_care import TechCard
from app.models.hr_ops import HrAuditEvent
from app.models.user import UserRole
from tests.test_care_api import (
    OUT_OF_SCOPE,
    care_on,  # noqa: F401  (fixture)
    headers,
    make_client,
    make_contract,
    make_user,
)

pytestmark = pytest.mark.asyncio


async def _unlinked_card(client_id: int, person_name: str, day: date) -> int:
    async with AsyncSessionLocal() as db:
        card = TechCard(
            client_id=client_id,
            contract_id=None,
            interview_on=day,
            is_draft=False,
            status="ok",
            compass_person_name=person_name,
            compass_card_id=uuid.uuid4(),
        )
        db.add(card)
        await db.commit()
        return card.id


async def _candidate_name(contract_id: int) -> str:
    async with AsyncSessionLocal() as db:
        first, last = (
            await db.execute(
                select(Candidate.name, Candidate.lastname)
                .join(Contract, Contract.candidate_id == Candidate.id)
                .where(Contract.id == contract_id)
            )
        ).one()
        return f"{first} {last}"


async def test_list_suggests_contracts_and_link_saves_once(app_client, care_on) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    other_client = await make_client()
    # Osoba z dwoma kontraktami u klienta — import nie wiedział, który.
    first_id, _ = await make_contract(client_id, started_days_ago=200)
    name = await _candidate_name(first_id)
    foreign_id, _ = await make_contract(other_client)
    today = business_today()
    card_id = await _unlinked_card(
        client_id, name.upper() + " [ACTIVE]", today - timedelta(days=5)
    )
    stranger_card = await _unlinked_card(client_id, "Nikt Taki", today)

    listed = await app_client.get(
        f"/api/care/clients/{client_id}/tech-cards/unlinked", headers=headers(dl)
    )
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["can_link"] is True
    items = {item["id"]: item for item in body["items"]}
    assert [s["id"] for s in items[card_id]["suggestions"]] == [first_id]
    assert items[card_id]["suggestions"][0]["candidate_name"] == name
    assert items[stranger_card]["suggestions"] == []
    assert first_id in {c["id"] for c in body["contracts"]}
    assert foreign_id not in {c["id"] for c in body["contracts"]}

    wrong = await app_client.post(
        f"/api/care/tech-cards/{card_id}/link",
        headers=headers(dl),
        json={"contract_id": foreign_id},
    )
    # Kontrakt cudzego klienta — DL nie ma go w portfelu, więc 403 z zakresu.
    assert wrong.status_code in (403, 422)

    linked = await app_client.post(
        f"/api/care/tech-cards/{card_id}/link",
        headers=headers(dl),
        json={"contract_id": first_id},
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["contract_id"] == first_id

    again = await app_client.post(
        f"/api/care/tech-cards/{card_id}/link",
        headers=headers(dl),
        json={"contract_id": first_id},
    )
    assert again.status_code == 409

    after = await app_client.get(
        f"/api/care/clients/{client_id}/tech-cards/unlinked", headers=headers(dl)
    )
    assert [item["id"] for item in after.json()["items"]] == [stranger_card]
    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_type == "tech_card",
                HrAuditEvent.entity_id == str(card_id),
            )
        )
        assert event.action == "care.tech_card_linked"
        assert event.details == {"contract_id": first_id, "suggested": True}


async def test_admin_cannot_link_contract_of_another_client(
    app_client, care_on
) -> None:
    admin = await make_user(UserRole.admin)
    client_id = await make_client()
    other_client = await make_client()
    foreign_id, _ = await make_contract(other_client)
    card_id = await _unlinked_card(client_id, "Anna Przykładowa", business_today())

    refused = await app_client.post(
        f"/api/care/tech-cards/{card_id}/link",
        headers=headers(admin),
        json={"contract_id": foreign_id},
    )
    assert refused.status_code == 422
    assert "innego klienta" in refused.json()["detail"]


async def test_reader_without_care_role_sees_list_but_cannot_link(
    app_client, care_on
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    finance = await make_user(UserRole.finance)
    client_id = await make_client(dl=dl)
    contract_id, _ = await make_contract(client_id)
    card_id = await _unlinked_card(client_id, "Ewa Przykładowa", business_today())

    listed = await app_client.get(
        f"/api/care/clients/{client_id}/tech-cards/unlinked", headers=headers(finance)
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["can_link"] is False
    refused = await app_client.post(
        f"/api/care/tech-cards/{card_id}/link",
        headers=headers(finance),
        json={"contract_id": contract_id},
    )
    assert refused.status_code == 403

    foreign_dl = await make_user(UserRole.delivery_lead)
    out = await app_client.get(
        f"/api/care/clients/{client_id}/tech-cards/unlinked",
        headers=headers(foreign_dl),
    )
    assert out.status_code == 403
    assert out.json()["detail"] == OUT_OF_SCOPE
