"""Poprawka i anulowanie protokołu sprzętu (decyzja Artura 28.10.2026).

Poprawka tylko przed podpisem (``oczekuje``), unieważnia wysłany link
i zostawia numer. Anulowanie — przed potwierdzeniem; wydanie wraca na stan,
zwrot przywraca wydania. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlparse

import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.equipment import EquipmentTask
from app.models.hr_ops import HrAuditEvent
from tests.test_equipment_api import (
    _contract,
    _drop_contract,
    _headers,
    _issued_protocol,
    _item,
    _model,
    make_people,
    modules_state,
)

PUBLIC = "/api/public/equipment-protocols"


@pytest_asyncio.fixture
async def modules_on():
    async with modules_state(True):
        yield


@pytest_asyncio.fixture
async def people():
    return await make_people()


async def _issue(app_client, headers, holder: dict, lines: list[dict]) -> dict:
    response = await app_client.post(
        "/api/equipment/issue", json={**holder, "lines": lines}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()["protocol"]


async def _link_token(app_client, headers, protocol_id: int) -> str:
    response = await app_client.post(
        f"/api/equipment/protocols/{protocol_id}/link", headers=headers
    )
    assert response.status_code == 200, response.text
    return urlparse(response.json()["url"]).path.rsplit("/", 1)[-1]


async def _item_status(app_client, headers, item_id: int) -> str:
    response = await app_client.get(f"/api/equipment/items/{item_id}", headers=headers)
    return response.json()["status"]


async def test_correction_changes_fields_keeps_number_and_revokes_link(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    laptop_model = await _model(app_client, headers, "laptop", "2589.00")
    sim_model = await _model(app_client, headers, "karta_sim")
    laptop = await _item(app_client, headers, laptop_model["id"])
    sim = await _item(
        app_client, headers, sim_model["id"], phone_number="500" + _digits()
    )
    protocol = await _issue(
        app_client,
        headers,
        {"holder_kind": "user", "holder_id": people["worker"].id},
        [{"item_id": laptop["id"], "accessories": "zasilacz"}, {"item_id": sim["id"]}],
    )
    token = await _link_token(app_client, headers, protocol["id"])
    assert (await app_client.get(f"{PUBLIC}/{token}")).status_code == 200

    detail = (
        await app_client.get(
            f"/api/equipment/protocols/{protocol['id']}", headers=headers
        )
    ).json()
    assert detail["lines"][0]["accessories"] == "zasilacz"
    assert detail["lines"][0]["name"] == (
        f"{detail['lines'][0]['base_name']} zasilacz"
    )

    new_date = business_today() - timedelta(days=1)
    if new_date.year != business_today().year:
        new_date = business_today()
    fixed = await app_client.patch(
        f"/api/equipment/protocols/{protocol['id']}",
        json={
            "protocol_date": new_date.isoformat(),
            "holder_name": "  Anna   Przykładowa-Nowak ",
            "lines": [
                {"position": 1, "unit_value": "1999.50", "accessories": "torba"},
            ],
        },
        headers=headers,
    )
    assert fixed.status_code == 200, fixed.text
    body = fixed.json()
    assert body["number"] == protocol["number"]
    assert body["status"] == "oczekuje"
    assert body["protocol_date"] == new_date.isoformat()
    assert body["holder"]["name"] == "Anna Przykładowa-Nowak"
    assert body["total_value"] == "1999.50"
    assert body["lines"][0]["name"].endswith(" torba")
    assert "zasilacz" not in body["lines"][0]["name"]
    assert body["link_revoked"] is True
    assert body["link"] is None
    # Osoba z linku nie podpisze starej treści.
    assert (await app_client.get(f"{PUBLIC}/{token}")).status_code == 404

    # D6: karta SIM bez wartości; pozycji nie dodaje się.
    sim_value = await app_client.patch(
        f"/api/equipment/protocols/{protocol['id']}",
        json={"lines": [{"position": 2, "unit_value": "10.00"}]},
        headers=headers,
    )
    assert sim_value.status_code == 422
    extra = await app_client.patch(
        f"/api/equipment/protocols/{protocol['id']}",
        json={"lines": [{"position": 3, "unit_value": "10.00"}]},
        headers=headers,
    )
    assert extra.status_code == 422
    secret = await app_client.patch(
        f"/api/equipment/protocols/{protocol['id']}",
        json={"lines": [{"position": 1, "accessories": "PIN 1234"}]},
        headers=headers,
    )
    assert secret.status_code == 422

    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(HrAuditEvent).where(
                HrAuditEvent.entity_type == "equipment_protocol",
                HrAuditEvent.entity_id == str(protocol["id"]),
                HrAuditEvent.action == "protocol_corrected",
            )
        )
        task = await db.scalar(
            select(EquipmentTask).where(
                EquipmentTask.source_key == f"protocol:{protocol['id']}:podpis"
            )
        )
    assert event is not None
    assert event.details["changes"]["lines"]["1"]["unit_value"] == [
        "2589.00",
        "1999.50",
    ]
    assert task.title == "Podpis protokołu: Anna Przykładowa-Nowak"


async def test_signed_protocol_cannot_be_corrected(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    protocol = await _issued_protocol(app_client, people)
    token = await _link_token(app_client, headers, protocol["id"])
    signed = await app_client.post(
        f"{PUBLIC}/{token}/sign", json={"signer_name": "Anna Przykładowa", "accepted": True}
    )
    assert signed.status_code == 200, signed.text
    refused = await app_client.patch(
        f"/api/equipment/protocols/{protocol['id']}",
        json={"holder_name": "Ktoś Inny"},
        headers=headers,
    )
    assert refused.status_code == 409
    assert "zrób zwrot i nowe wydanie" in refused.json()["detail"]


async def test_cancelled_issue_puts_items_back_and_drops_contract_rows(
    app_client, app_auth_headers, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    ids = await _contract(start=business_today() - timedelta(days=5), end=None)
    try:
        model = await _model(app_client, headers, "laptop", "3000.00")
        laptop = await _item(app_client, headers, model["id"])
        protocol = await _issue(
            app_client,
            headers,
            {"holder_kind": "contract", "holder_id": ids["id"]},
            [{"item_id": laptop["id"]}],
        )
        token = await _link_token(app_client, headers, protocol["id"])
        assert await _item_status(app_client, headers, laptop["id"]) == "wydany"

        no_reason = await app_client.post(
            f"/api/equipment/protocols/{protocol['id']}/cancel",
            json={"reason": "  "},
            headers=headers,
        )
        assert no_reason.status_code == 422
        cancelled = await app_client.post(
            f"/api/equipment/protocols/{protocol['id']}/cancel",
            json={"reason": "Ćwiczenie recepcji"},
            headers=headers,
        )
        assert cancelled.status_code == 200, cancelled.text
        body = cancelled.json()
        assert body["status"] == "anulowany"
        assert body["cancel_reason"] == "Ćwiczenie recepcji"
        assert body["cancelled_at"]

        assert await _item_status(app_client, headers, laptop["id"]) == "na_stanie"
        rows = (
            await app_client.get(
                f"/api/contracts/{ids['id']}/equipment", headers=app_auth_headers
            )
        ).json()
        assert rows == []
        assert (await app_client.get(f"{PUBLIC}/{token}")).status_code == 404
        async with AsyncSessionLocal() as db:
            task = await db.scalar(
                select(EquipmentTask).where(
                    EquipmentTask.source_key == f"protocol:{protocol['id']}:podpis"
                )
            )
        assert task.status == "anulowane"

        waiting = (
            await app_client.get(
                "/api/equipment/protocols?status=waiting", headers=headers
            )
        ).json()["items"]
        assert protocol["id"] not in {p["id"] for p in waiting}
        unsigned = (
            await app_client.get("/api/equipment/items?unsigned=true", headers=headers)
        ).json()
        assert laptop["id"] not in {row["id"] for row in unsigned["items"]}

        again = await app_client.post(
            f"/api/equipment/protocols/{protocol['id']}/cancel",
            json={"reason": "Drugi raz"},
            headers=headers,
        )
        assert again.status_code == 409
        # Egzemplarz da się wydać od nowa.
        await _issue(
            app_client,
            headers,
            {"holder_kind": "contract", "holder_id": ids["id"]},
            [{"item_id": laptop["id"]}],
        )
    finally:
        await _drop_contract(ids)


async def test_cancelled_return_restores_the_issue(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    model = await _model(app_client, headers, "telefon", "900.00")
    phone = await _item(app_client, headers, model["id"])
    await _issue(
        app_client,
        headers,
        {"holder_kind": "user", "holder_id": people["worker"].id},
        [{"item_id": phone["id"]}],
    )
    mine = await app_client.get("/api/equipment/me", headers=_headers(people["worker"]))
    assignment_id = mine.json()["active"][0]["assignment_id"]
    returned = await app_client.post(
        "/api/equipment/return",
        json={"lines": [{"assignment_id": assignment_id, "condition": "uszkodzony"}]},
        headers=headers,
    )
    assert returned.status_code == 201, returned.text
    back = returned.json()["protocol"]
    assert await _item_status(app_client, headers, phone["id"]) == "serwis"

    # Poprawka stanu przy zwrocie idzie za egzemplarzem.
    fixed = await app_client.patch(
        f"/api/equipment/protocols/{back['id']}",
        json={"lines": [{"position": 1, "condition": "sprawny", "notes": "Rysa"}]},
        headers=headers,
    )
    assert fixed.status_code == 200, fixed.text
    assert fixed.json()["lines"][0]["condition"] == "sprawny"
    assert await _item_status(app_client, headers, phone["id"]) == "na_stanie"

    cancelled = await app_client.post(
        f"/api/equipment/protocols/{back['id']}/cancel",
        json={"reason": "Pomyłka — telefon nie wrócił"},
        headers=headers,
    )
    assert cancelled.status_code == 200, cancelled.text
    assert await _item_status(app_client, headers, phone["id"]) == "wydany"
    active = (
        await app_client.get("/api/equipment/me", headers=_headers(people["worker"]))
    ).json()["active"]
    assert [row["assignment_id"] for row in active] == [assignment_id]


async def test_confirmed_protocol_cannot_be_cancelled(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    protocol = await _issued_protocol(app_client, people)
    confirmed = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/confirm",
        json={"method": "papier"},
        headers=headers,
    )
    assert confirmed.status_code == 200
    refused = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/cancel",
        json={"reason": "Pomyłka"},
        headers=headers,
    )
    assert refused.status_code == 409


async def test_issue_with_returned_items_cannot_be_cancelled(
    app_client, modules_on, people
) -> None:
    headers = _headers(people["reception"])
    protocol = await _issued_protocol(app_client, people)
    mine = await app_client.get("/api/equipment/me", headers=_headers(people["worker"]))
    assignment_id = next(
        row["assignment_id"]
        for row in mine.json()["active"]
        if row["issue_protocol_id"] == protocol["id"]
    )
    returned = await app_client.post(
        "/api/equipment/return",
        json={"lines": [{"assignment_id": assignment_id, "condition": "sprawny"}]},
        headers=headers,
    )
    assert returned.status_code == 201
    refused = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/cancel",
        json={"reason": "Pomyłka"},
        headers=headers,
    )
    assert refused.status_code == 409
    assert "najpierw anuluj zwrot" in refused.json()["detail"]


async def test_correction_and_cancel_need_the_equipment_permission(
    app_client, modules_on, people
) -> None:
    protocol = await _issued_protocol(app_client, people)
    for persona in ("hr", "recruiter", "delivery", "worker"):
        headers = _headers(people[persona])
        patch = await app_client.patch(
            f"/api/equipment/protocols/{protocol['id']}",
            json={"holder_name": "Ktoś Inny"},
            headers=headers,
        )
        cancel = await app_client.post(
            f"/api/equipment/protocols/{protocol['id']}/cancel",
            json={"reason": "Pomyłka"},
            headers=headers,
        )
        assert (patch.status_code, cancel.status_code) == (403, 403), persona
    admin = await app_client.post(
        f"/api/equipment/protocols/{protocol['id']}/cancel",
        json={"reason": "Pomyłka"},
        headers=_headers(people["admin"]),
    )
    assert admin.status_code == 200


def _digits() -> str:
    import uuid

    return str(100_000 + uuid.uuid4().int % 899_999)
