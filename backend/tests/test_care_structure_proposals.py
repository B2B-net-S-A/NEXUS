"""Propozycje struktury u klienta i akcept DL (decyzja Artura 18.10.2026).

Zakres: odczyt niczego nie zapisuje; propozycja z pola „Line Manager” jest
pewna, z samego hiring managera — niepewna; „Zatwierdź” wpisuje menedżera
na kontrakt i nie nadpisuje menedżera wpisanego w międzyczasie; „Zmień” na
osobę innego klienta = 422; „Pomiń” chowa propozycję, a inna osoba ją
przywraca; Delivery Lead nie czyta ani nie zatwierdza u cudzego klienta,
rekruter i Finanse nie zatwierdzają; „Podlega pod” z propozycji nie zamyka
pętli; dzwonek „uzupełnij strukturę” do DL klienta raz na 7 dni.

Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

import app.models  # noqa: F401  (rejestracja wszystkich mapperów)
from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.models.client_structure import ClientStructureSkip
from app.models.contract import Contract
from app.models.contract_care import CONTACTS_ORG
from app.models.job import Job, JobStatus
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from app.services.care import structure_proposals
from tests.test_care_api import headers, make_client, make_user
from tests.test_care_client_people import (  # noqa: F401  (fixture modułów)
    care_module,
    make_area,
    make_consultant,
    make_contact,
)

pytestmark = pytest.mark.asyncio

OUT_OF_SCOPE_STATUS = 403


def _url(client_id: int, rest: str = "") -> str:
    return f"/api/care/clients/{client_id}/structure-proposals{rest}"


def _row(payload: dict, contract_id: int) -> dict:
    for row in payload["managers"]:
        if row["contract_id"] == contract_id:
            return row
    raise AssertionError(f"brak kontraktu {contract_id} w propozycjach")


async def _manager_of(contract_id: int):
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(Contract.client_pm_contact_id).where(Contract.id == contract_id)
        )


async def _set_job_hm(contract_id: int, client_id: int, contact_id: int) -> None:
    async with AsyncSessionLocal() as db:
        job = Job(
            title="Analityk danych",
            description="Opis",
            client_id=client_id,
            status=JobStatus.published,
            hiring_manager_contact_id=contact_id,
        )
        db.add(job)
        await db.flush()
        await db.execute(
            update(Contract).where(Contract.id == contract_id).values(job_id=job.id)
        )
        await db.commit()


async def test_proposals_sources_confidence_and_apply(app_client, care_module) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    anna = await make_contact(client_id, "Anna Nowak", position="Kierownik Zespołu")
    jan = await make_contact(client_id, "Jan Kowalski", position="Dyrektor IT")
    certain = await make_consultant(client_id, line_manager="Nowak Anna")
    hm_only = await make_consultant(client_id)
    await _set_job_hm(hm_only, client_id, jan)
    nothing = await make_consultant(client_id)

    read = await app_client.get(_url(client_id), headers=headers(dl))
    assert read.status_code == 200, read.text
    payload = read.json()
    assert payload["can_apply_managers"] is True
    row = _row(payload, certain)
    assert row["confidence"] == "certain"
    assert row["proposal"]["contact"]["id"] == anna
    assert [s["source"] for s in row["proposal"]["sources"]] == ["line_manager"]
    assert _row(payload, hm_only)["confidence"] == "uncertain"
    assert (
        _row(payload, hm_only)["proposal"]["sources"][0]["source"]
        == "job_hiring_manager"
    )
    assert _row(payload, nothing)["confidence"] == "none"
    assert payload["counts"]["certain"] == 1
    assert payload["counts"]["without_manager"] == 3
    # Odczyt niczego nie zapisuje.
    assert await _manager_of(certain) is None

    applied = await app_client.post(
        _url(client_id, "/managers"),
        headers=headers(dl),
        json={"items": [{"contract_id": certain, "contact_id": anna}]},
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == [certain]
    assert await _manager_of(certain) == anna
    assert certain not in {
        r["contract_id"] for r in applied.json()["client"]["managers"]
    }

    # Drzewo „Struktura u klienta” pokazuje konsultanta pod menedżerką.
    org = await app_client.get(
        f"/api/care/clients/{client_id}/org", headers=headers(dl)
    )
    people = {p["id"]: p for d in org.json()["departments"] for p in d["people"]}
    assert [c["contract_id"] for c in people[anna]["consultants"]] == [certain]

    summary = await app_client.get("/api/care/structure-proposals", headers=headers(dl))
    mine = [r for r in summary.json()["items"] if r["client_id"] == client_id]
    assert mine and mine[0]["without_manager"] == 2


async def test_apply_does_not_overwrite_a_manager_set_meanwhile(
    app_client, care_module
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    anna = await make_contact(client_id, "Anna Nowak")
    jan = await make_contact(client_id, "Jan Kowalski")
    contract_id = await make_consultant(client_id, manager_id=jan)
    response = await app_client.post(
        _url(client_id, "/managers"),
        headers=headers(dl),
        json={"items": [{"contract_id": contract_id, "contact_id": anna}]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["conflicts"] == [
        {"contract_id": contract_id, "reason": "manager_set"}
    ]
    assert await _manager_of(contract_id) == jan


async def test_change_validates_the_client_of_person_and_contract(
    app_client, care_module
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    other_client = await make_client(dl=dl)
    foreign_contact = await make_contact(other_client, "Ewa Zielińska")
    contract_id = await make_consultant(client_id)
    foreign_contract = await make_consultant(other_client)
    own_contact = await make_contact(client_id, "Piotr Wiśniewski")

    for items in (
        [{"contract_id": contract_id, "contact_id": foreign_contact}],
        [{"contract_id": foreign_contract, "contact_id": own_contact}],
        [{"contract_id": contract_id}],
        [
            {
                "contract_id": contract_id,
                "contact_id": own_contact,
                "new_person_name": "Ola Nowa",
            }
        ],
    ):
        response = await app_client.post(
            _url(client_id, "/managers"), headers=headers(dl), json={"items": items}
        )
        assert response.status_code == 422, (items, response.text)
    assert await _manager_of(contract_id) is None

    created = await app_client.post(
        _url(client_id, "/managers"),
        headers=headers(dl),
        json={
            "items": [
                {
                    "contract_id": contract_id,
                    "new_person_name": "Ola Nowa",
                    "new_person_position": "Kierownik",
                }
            ]
        },
    )
    assert created.status_code == 200, created.text
    names = {p["id"]: p["name"] for p in created.json()["client"]["people"]}
    assert names[await _manager_of(contract_id)] == "Ola Nowa"


async def test_skip_hides_until_a_different_person_is_proposed(
    app_client, care_module
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    anna = await make_contact(client_id, "Anna Nowak")
    jan = await make_contact(client_id, "Jan Kowalski")
    contract_id = await make_consultant(client_id, line_manager="Anna Nowak")

    skipped = await app_client.put(
        _url(client_id, f"/managers/{contract_id}/skip"),
        headers=headers(dl),
        json={"proposed_contact_id": anna},
    )
    assert skipped.status_code == 200, skipped.text
    row = _row(skipped.json(), contract_id)
    assert row["skipped"] is not None
    assert skipped.json()["counts"]["open"] == 0

    # Automat wskazuje teraz kogoś innego — pozycja wraca.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == contract_id)
            .values(line_manager="Jan Kowalski")
        )
        await db.commit()
    back = await app_client.get(_url(client_id), headers=headers(dl))
    row = _row(back.json(), contract_id)
    assert row["skipped"] is None and row["proposal"]["contact"]["id"] == jan

    await app_client.put(
        _url(client_id, f"/managers/{contract_id}/skip"),
        headers=headers(dl),
        json={"proposed_contact_id": jan},
    )
    restored = await app_client.delete(
        _url(client_id, f"/managers/{contract_id}/skip"), headers=headers(dl)
    )
    assert restored.status_code == 200
    assert _row(restored.json(), contract_id)["skipped"] is None
    async with AsyncSessionLocal() as db:
        count = await db.scalar(
            select(func.count())
            .select_from(ClientStructureSkip)
            .where(ClientStructureSkip.contract_id == contract_id)
        )
    assert count == 0


async def test_scope_and_roles(app_client, care_module) -> None:
    dl = await make_user(UserRole.delivery_lead)
    own = await make_client(dl=dl)
    foreign = await make_client()
    contact = await make_contact(foreign, "Anna Nowak")
    contract_id = await make_consultant(foreign)
    body = {"items": [{"contract_id": contract_id, "contact_id": contact}]}

    assert (
        await app_client.get(_url(foreign), headers=headers(dl))
    ).status_code == OUT_OF_SCOPE_STATUS
    assert (
        await app_client.post(
            _url(foreign, "/managers"), headers=headers(dl), json=body
        )
    ).status_code == OUT_OF_SCOPE_STATUS
    summary = await app_client.get("/api/care/structure-proposals", headers=headers(dl))
    ids = {row["client_id"] for row in summary.json()["items"]}
    assert foreign not in ids
    assert (await app_client.get(_url(own), headers=headers(dl))).status_code == 200

    recruiter = await make_user(UserRole.recruiter)
    finance = await make_user(UserRole.finance)
    tcm = await make_user(UserRole.talent_community_manager)
    for user in (recruiter, finance):
        assert (
            await app_client.get(_url(foreign), headers=headers(user))
        ).status_code == 403
        # Zapis „Podlega pod” też niesie propozycje — poza kręgiem D11 odmowa.
        skip = await app_client.put(
            _url(foreign, f"/reports-to/{contact}/skip"), headers=headers(user), json={}
        )
        assert skip.status_code == 403, skip.text
    # TCM czyta (opiekun), ale menedżera zatwierdza Delivery Lead albo admin.
    tcm_read = await app_client.get(_url(foreign), headers=headers(tcm))
    assert tcm_read.status_code == 200, tcm_read.text
    assert tcm_read.json()["can_apply_managers"] is False
    denied = await app_client.post(
        _url(foreign, "/managers"), headers=headers(tcm), json=body
    )
    assert denied.status_code == 403
    assert await _manager_of(contract_id) is None

    admin = await make_user(UserRole.admin)
    ok = await app_client.post(
        _url(foreign, "/managers"), headers=headers(admin), json=body
    )
    assert ok.status_code == 200, ok.text
    assert await _manager_of(contract_id) == contact


async def test_reports_to_proposal_applies_without_closing_a_loop(
    app_client, care_module
) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    area = await make_area(client_id, "Płatności")
    director = await make_contact(
        client_id, "Jan Kowalski", position="Dyrektor Płatności", area_id=area
    )
    lead = await make_contact(
        client_id, "Anna Nowak", position="Kierownik Zespołu", area_id=area
    )
    await make_consultant(client_id, manager_id=lead)

    payload = (await app_client.get(_url(client_id), headers=headers(dl))).json()
    proposals = {row["contact"]["id"]: row for row in payload["reports_to"]}
    assert proposals[lead]["confidence"] == "certain"
    assert proposals[lead]["proposal"]["contact"]["id"] == director
    assert payload["can_apply_org"] is True

    applied = await app_client.post(
        _url(client_id, "/reports-to"),
        headers=headers(dl),
        json={
            "items": [
                {"contact_id": lead, "reports_to_contact_id": director},
                # Dyrektor pod kierowniczką zamknąłby pętlę — odrzucony, reszta zapisana.
                {"contact_id": director, "reports_to_contact_id": lead},
            ]
        },
    )
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body["applied"] == [lead]
    assert [r["contact_id"] for r in body["rejected"]] == [director]
    async with AsyncSessionLocal() as db:
        chain = dict(
            (
                await db.execute(
                    select(
                        CONTACTS_ORG.c.id, CONTACTS_ORG.c.reports_to_contact_id
                    ).where(CONTACTS_ORG.c.id.in_([lead, director]))
                )
            ).all()
        )
    assert chain == {lead: director, director: None}


async def test_reminder_goes_to_client_delivery_lead_once_a_week(care_module) -> None:
    dl = await make_user(UserRole.delivery_lead)
    client_id = await make_client(dl=dl)
    await make_contact(client_id, "Anna Nowak")
    await make_consultant(client_id, line_manager="Anna Nowak")
    now = local_now()

    async def sent_to_dl() -> int:
        async with AsyncSessionLocal() as db:
            return int(
                await db.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(
                        Notification.user_id == dl.id,
                        Notification.notification_type
                        == NotificationType.care_client_structure,
                        Notification.related_entity_id == client_id,
                    )
                )
                or 0
            )

    async with AsyncSessionLocal() as db:
        counts = await structure_proposals.remind(db, now=now)
        await db.commit()
    assert counts["structure_sent"] >= 1
    assert await sent_to_dl() == 1
    async with AsyncSessionLocal() as db:
        link = await db.scalar(
            select(Notification.link).where(
                Notification.user_id == dl.id,
                Notification.notification_type
                == NotificationType.care_client_structure,
            )
        )
    assert link == f"/care?tab=structure&client={client_id}"

    async with AsyncSessionLocal() as db:
        await structure_proposals.remind(db, now=now + timedelta(days=1))
        await db.commit()
    assert await sent_to_dl() == 1
