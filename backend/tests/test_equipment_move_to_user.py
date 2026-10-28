"""„Przepisz na konto”: sprzęt osoby spoza NEXUSA przechodzi na jej nowe konto.

Nowa osoba w firmie dostaje sprzęt jako osoba spoza NEXUSA, zanim powstanie
konto (decyzja Artura 28.10.2026, wariant B). Dane fikcyjne: osoby
„Przykładowe”, numery „TEST…”.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.equipment import (
    EquipmentAssignment,
    EquipmentProtocol,
    EquipmentTask,
)
from app.models.hr_ops import HrAuditEvent
from tests.test_equipment_api import (
    _headers,
    _item,
    _model,
    _tag,
    _user,
    make_people,
    modules_state,
)


@pytest_asyncio.fixture
async def modules_on():
    async with modules_state(True):
        yield


@pytest_asyncio.fixture
async def people():
    return await make_people()


async def _external(app_client, headers) -> dict:
    response = await app_client.post(
        "/api/equipment/external-people",
        json={"full_name": f"Karolina Przykładowa {_tag()}", "note": "nowa w biurze"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _issue(app_client, headers, person_id: int, category: str) -> dict:
    model = await _model(app_client, headers, category, "900.00")
    item = await _item(app_client, headers, model["id"])
    issued = await app_client.post(
        "/api/equipment/issue",
        json={
            "holder_kind": "external",
            "holder_id": person_id,
            "lines": [{"item_id": item["id"]}],
        },
        headers=headers,
    )
    assert issued.status_code == 201, issued.text
    return issued.json()["protocol"]


def _url(person_id: int) -> str:
    return f"/api/equipment/external-people/{person_id}/move-to-user"


async def test_move_carries_items_tasks_and_open_protocols_to_the_account(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    person = await _external(app_client, headers)
    confirmed = await _issue(app_client, headers, person["id"], "laptop")
    done = await app_client.post(
        f"/api/equipment/protocols/{confirmed['id']}/confirm",
        json={"method": "papier"},
        headers=headers,
    )
    assert done.status_code == 200, done.text
    waiting = await _issue(app_client, headers, person["id"], "monitor")
    account = people["worker"]

    moved = await app_client.post(
        _url(person["id"]), json={"user_id": account.id}, headers=headers
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert body["holder"] == {
        "kind": "user",
        "id": account.id,
        "name": account.name,
        "email": account.email,
        "detail": "Konto NEXUSA",
    }
    assert (body["assignments"], body["protocols"], body["confirmed_protocols"]) == (
        2,
        1,
        1,
    )
    assert body["tasks"] == 1  # zadanie podpisu protokołu, który czeka

    on_account = await app_client.get(
        f"/api/equipment/holders/user/{account.id}", headers=headers
    )
    assert len(on_account.json()["active"]) == 2
    left = await app_client.get(
        f"/api/equipment/holders/external/{person['id']}", headers=headers
    )
    assert left.json()["active"] == []

    async with AsyncSessionLocal() as db:
        open_protocol = await db.get(EquipmentProtocol, waiting["id"])
        closed_protocol = await db.get(EquipmentProtocol, confirmed["id"])
        task = await db.scalar(
            select(EquipmentTask).where(
                EquipmentTask.source_key == f"protocol:{waiting['id']}:podpis"
            )
        )
        events = (
            await db.scalars(
                select(HrAuditEvent).where(
                    HrAuditEvent.action.in_(
                        ("equipment_moved_to_user", "equipment_holder_moved_to_user")
                    ),
                    HrAuditEvent.subject_user_id == account.id,
                )
            )
        ).all()
    # Czekający protokół idzie za sprzętem, migawka nazwiska zostaje.
    assert (open_protocol.user_id, open_protocol.external_person_id) == (
        account.id,
        None,
    )
    assert open_protocol.holder_name == person["full_name"]
    # Potwierdzony zostaje przy osobie spoza — z migawką i wpisem w dzienniku.
    assert (closed_protocol.user_id, closed_protocol.external_person_id) == (
        None,
        person["id"],
    )
    assert closed_protocol.holder_name == person["full_name"]
    assert (task.user_id, task.external_person_id) == (account.id, None)
    by_action = {event.action: event for event in events}
    trail = by_action["equipment_holder_moved_to_user"]
    assert trail.entity_type == "equipment_protocol"
    assert trail.entity_id == str(confirmed["id"])
    assert trail.details["from_external_person_id"] == person["id"]
    summary = by_action["equipment_moved_to_user"]
    assert summary.details["confirmed_protocol_ids"] == [confirmed["id"]]
    assert summary.details["protocol_ids"] == [waiting["id"]]


async def test_person_without_items_is_refused(app_client, modules_on, people) -> None:
    headers = _headers(people["reception"])
    person = await _external(app_client, headers)
    refused = await app_client.post(
        _url(person["id"]), json={"user_id": people["worker"].id}, headers=headers
    )
    assert refused.status_code == 409
    assert "nie ma niezwróconego sprzętu" in refused.json()["detail"]


async def test_inactive_account_is_refused_and_nothing_moves(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    person = await _external(app_client, headers)
    await _issue(app_client, headers, person["id"], "laptop")
    async with AsyncSessionLocal() as db:
        gone = await _user(db, "employee", name=f"Odeszła Przykładowa {_tag()}")
        gone.is_active = False
        await db.commit()
    refused = await app_client.post(
        _url(person["id"]), json={"user_id": gone.id}, headers=headers
    )
    assert refused.status_code == 409
    assert "nieaktywne" in refused.json()["detail"]
    async with AsyncSessionLocal() as db:
        still = await db.scalar(
            select(EquipmentAssignment).where(
                EquipmentAssignment.external_person_id == person["id"],
                EquipmentAssignment.returned_at.is_(None),
            )
        )
    assert still is not None


async def test_only_equipment_permission_moves(app_client, modules_on, people) -> None:
    headers = _headers(people["reception"])
    person = await _external(app_client, headers)
    await _issue(app_client, headers, person["id"], "laptop")
    for key in ("recruiter", "hr", "delivery"):
        refused = await app_client.post(
            _url(person["id"]),
            json={"user_id": people["worker"].id},
            headers=_headers(people[key]),
        )
        assert refused.status_code == 403, key
    missing = await app_client.post(
        _url(person["id"] + 10_000_000),
        json={"user_id": people["worker"].id},
        headers=headers,
    )
    assert missing.status_code == 404
