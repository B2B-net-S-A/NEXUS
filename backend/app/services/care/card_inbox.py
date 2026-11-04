"""„Karty do połączenia” — karty z Compassa bez kontraktu i ich propozycje.

Import łączy kartę z kontraktem sam tylko przy pewnej parze
(``card_linking``); reszta czeka przy kliencie z pustym ``contract_id``.
Lista liczy propozycje przy odczycie (kontrakt dodany w NEXUSIE po imporcie
też się pojawi) i niczego nie zapisuje. „Połącz” zapisuje kontrakt na karcie —
tylko kontrakt tego samego klienta (po scaleniu), bez anulowanych i szkiców,
i tylko kartę jeszcze bez kontraktu (raz połączonej nie przepinamy tą drogą).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract
from app.models.contract_care import ClientArea, TechCard
from app.models.user import User
from app.services.care import access as care_access
from app.services.care import card_linking, records, tech_map
from app.services.care import skills as care_skills
from app.services.hr import audit

#: Ile kontraktów klienta pokazać w wyborze „Inny kontrakt”.
MAX_CLIENT_CONTRACTS = 500

CARD_ALREADY_LINKED = "Karta jest już połączona z kontraktem."
CONTRACT_OTHER_CLIENT = "Ten kontrakt należy do innego klienta niż karta."
CONTRACT_NOT_LINKABLE = "Z anulowanym albo szkicem kontraktu karty nie łączymy."


def _contract_row(contract: care_access.CareContract) -> dict[str, Any]:
    return {
        "id": contract.id,
        "candidate_name": contract.candidate_name,
        "start_date": contract.start_date,
        "end_date": contract.end_date,
        "status": contract.status,
    }


async def _client_contracts(
    db: AsyncSession, client_ids: list[int]
) -> list[care_access.CareContract]:
    ids = (
        await db.scalars(
            select(Contract.id)
            .where(
                Contract.client_id.in_(client_ids),
                Contract.status.notin_(card_linking.SKIPPED_STATUSES),
            )
            .order_by(Contract.start_date.desc().nulls_last(), Contract.id.desc())
            .limit(MAX_CLIENT_CONTRACTS)
        )
    ).all()
    found = await care_access.contracts_by_id(db, ids)
    return [found[i] for i in ids if i in found]


async def unlinked_cards(db: AsyncSession, client_id: int) -> dict[str, Any]:
    client_ids = await tech_map.related_client_ids(db, client_id)
    cards = (
        await db.scalars(
            select(TechCard)
            .where(TechCard.client_id.in_(client_ids), TechCard.contract_id.is_(None))
            .order_by(TechCard.interview_on.desc(), TechCard.id.desc())
        )
    ).all()
    if not cards:
        return {"items": [], "contracts": []}
    final = (await card_linking.final_client_ids(db)).get(client_id, client_id)
    index = await card_linking.load_index(db, [final])
    contracts = await _client_contracts(db, client_ids)
    by_id = {contract.id: contract for contract in contracts}
    matches = {
        card.id: index.match(final, card.compass_person_name, card.interview_on)
        for card in cards
    }
    missing = {cid for match in matches.values() for cid in match.contract_ids} - set(
        by_id
    )
    by_id.update(await care_access.contracts_by_id(db, missing))
    area_ids = {card.client_area_id for card in cards if card.client_area_id}
    areas = (
        dict(
            (
                await db.execute(
                    select(ClientArea.id, ClientArea.name).where(
                        ClientArea.id.in_(sorted(area_ids))
                    )
                )
            ).all()
        )
        if area_ids
        else {}
    )
    authors = await care_access.user_names(db, [card.author_user_id for card in cards])
    card_skills, _ = await records.card_relations(db, [card.id for card in cards])
    skill_names = (await care_skills.load_dictionary(db)).names
    return {
        "items": [
            {
                "id": card.id,
                "interview_on": card.interview_on,
                "person_name": card.compass_person_name,
                "area": areas.get(card.client_area_id),
                "author": authors.get(card.author_user_id),
                "is_draft": card.is_draft,
                "skills": sorted(
                    skill_names.get(sid, "") for sid in card_skills.get(card.id, [])
                )[:8],
                "unrecognized_skills": list(card.unrecognized_skills or [])[:8],
                "suggestions": [
                    _contract_row(by_id[cid])
                    for cid in matches[card.id].contract_ids
                    if cid in by_id
                ],
            }
            for card in cards
        ],
        "contracts": [_contract_row(contract) for contract in contracts],
    }


async def link_card(
    db: AsyncSession,
    *,
    card_id: int,
    contract_id: int,
    user: User,
) -> TechCard:
    card = await db.get(TechCard, card_id, with_for_update=True)
    if card is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej karty.")
    await care_access.load_client(db, card.client_id, user)
    if card.contract_id is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, CARD_ALREADY_LINKED)
    contract = await care_access.load_contract(db, contract_id, user)
    finals = await card_linking.final_client_ids(db)
    card_client = finals.get(card.client_id, card.client_id)
    if finals.get(contract.client_id, contract.client_id) != card_client:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, CONTRACT_OTHER_CLIENT)
    if contract.status in {value.value for value in card_linking.SKIPPED_STATUSES}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, CONTRACT_NOT_LINKABLE)
    index = await card_linking.load_index(db, [card_client])
    suggested = (
        contract_id
        in index.match(
            card_client, card.compass_person_name, card.interview_on
        ).contract_ids
    )
    card.contract_id = contract.id
    audit.record(
        db,
        actor_user_id=user.id,
        subject_user_id=None,
        entity_type="tech_card",
        entity_id=card.id,
        action="care.tech_card_linked",
        details={"contract_id": contract.id, "suggested": suggested},
    )
    await db.flush()
    await tech_map.invalidate([card_client, card.client_id])
    return card
