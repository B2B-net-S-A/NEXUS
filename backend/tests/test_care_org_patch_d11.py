"""Zapis „Podlega pod” nie oddaje opinii klienta osobie spoza D11 (17.10.2026).

Finanse z nadanym „Klienci: dodawanie i edycja” dostają 403 na
``GET /api/care/clients/{id}/org`` (D11), ale ``PATCH …/contacts/{cid}``
przechodzi przez bramkę edycji kontaktów. Odpowiedź zapisu podlega tej samej
regule co odczyt: drzewo tak, opinie (``last_feedback``) i prośby o opinię
nie. Opiekun z D11 dostaje w odpowiedzi zapisu to samo co w odczycie.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.section_permission import UserActionOverride
from app.models.user import UserRole
from tests.test_care_api import headers, make_client, make_user
from tests.test_care_client_people import (  # noqa: F401 — fikstura
    add_session,
    care_module,
    make_consultant,
    make_contact,
)

pytestmark = pytest.mark.asyncio


def _people(org: dict) -> list[dict]:
    return [person for dept in org["departments"] for person in dept["people"]]


async def _world(dl=None) -> tuple[int, int, int, int]:
    client_id = await make_client(dl=dl)
    boss = await make_contact(client_id, "Anna Testowa")
    manager = await make_contact(client_id, "Ola Testowa")
    contract_id = await make_consultant(
        client_id, manager_id=manager, started_days_ago=200
    )
    # Ostatnia rozmowa sprzed kwartału — menedżer ma i opinię, i prośbę (D9).
    await add_session(
        client_id, manager, business_today() - timedelta(days=100), {contract_id: 2}
    )
    return client_id, boss, manager, contract_id


async def test_patch_org_hides_feedback_from_reader_denied_by_d11(
    app_client,
    care_module,  # noqa: F811
) -> None:
    finance = await make_user(UserRole.finance)
    async with AsyncSessionLocal() as db:
        db.add(
            UserActionOverride(
                user_id=finance.id, action="clients_edit", access="manage"
            )
        )
        await db.commit()
    client_id, boss, manager, contract_id = await _world()

    denied = await app_client.get(
        f"/api/care/clients/{client_id}/org", headers=headers(finance)
    )
    assert denied.status_code == 403, denied.text

    patched = await app_client.patch(
        f"/api/care/clients/{client_id}/contacts/{manager}",
        headers=headers(finance),
        json={"reports_to_contact_id": boss},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    people = {person["id"]: person for person in _people(body)}
    # Zapis przeszedł i drzewo jest w odpowiedzi…
    assert people[manager]["reports_to"]["id"] == boss
    assert [c["contract_id"] for c in people[manager]["consultants"]] == [contract_id]
    # …ale bez opinii i próśb o opinię (D11).
    assert body["requests"] == []
    assert all(person["last_feedback"] is None for person in people.values())
    assert all(person["feedback_request"] is None for person in people.values())
    assert all(
        consultant["last_feedback"] is None
        for person in people.values()
        for consultant in person["consultants"]
    )
    assert all(row["last_feedback"] is None for row in body["without_manager"])
    assert body["feedback_visible"] is False


async def test_patch_org_keeps_feedback_for_d11_reader(
    app_client,
    care_module,  # noqa: F811
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id, boss, manager, contract_id = await _world(dl=dl)

    read = await app_client.get(
        f"/api/care/clients/{client_id}/org", headers=headers(dl)
    )
    assert read.status_code == 200, read.text
    patched = await app_client.patch(
        f"/api/care/clients/{client_id}/contacts/{manager}",
        headers=headers(dl),
        json={"reports_to_contact_id": boss},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    person = {p["id"]: p for p in _people(body)}[manager]
    assert body["feedback_visible"] is True
    assert read.json()["feedback_visible"] is True
    assert person["last_feedback"] is not None
    assert person["consultants"][0]["last_feedback"] is not None
    assert person["feedback_request"] is not None
    assert [item["contact_id"] for item in body["requests"]] == [manager]
