"""Portal konsultanta: plik zbiorczy klienta nie wychodzi do konsultanta (z bazą).

Audyt 24.11.2026: czytniki rozliczenia@ zapisują ten sam protokół, arkusz albo
.eml koordynatora z godzinami wielu osób przy kontrakcie każdej z nich, a portal
dawał pobrać każdy dokument kontraktu. Konsultant pobiera tylko plik, który
wysłał sam (decyzja Artura z 24.11.2026). Skrzynka to atrapa, dane fikcyjne.
"""

from __future__ import annotations

import pytest
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.contract import Contract
from tests.care_announcements_seed import care_on, tag  # noqa: F401  (fixture'y)
from tests.consultant_portal_seed import (  # noqa: F401  (fixture'y)
    BASE,
    make_person,
    portal_restored,
    session_headers,
    set_portal,
)
from tests.test_consultant_portal_protocol_mail_db import _cez, texts  # noqa: F401
from tests.test_consultant_portal_zip_mail_db import (  # noqa: F401  (fixture'y)
    DOMAIN,
    FakeMailbox,
    _attachment,
    _config,
    _fresh_state,
    _message,
    _of_contract,
    _read,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("care_on")]

NAME = "CeZ protokół odbioru - wrzesień 2026-sig.pdf"


@pytest.fixture
async def pilot(portal_restored):  # noqa: F811
    await set_portal("pilot")
    yield


async def _named(person, first: str) -> str:
    last = f"Testowy{tag()}"
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Candidate)
            .where(Candidate.id == person.candidate_id)
            .values(name=first, lastname=last)
        )
        await db.commit()
    return f"{first} {last}"


async def _same_client(person, client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == person.contract_id)
            .values(client_id=client_id)
        )
        await db.commit()


async def _documents(client, headers) -> list[dict]:
    response = await client.get(f"{BASE}/finance/overview", headers=headers)
    assert response.status_code == 200, response.text
    return [doc for month in response.json()["months"] for doc in month["documents"]]


@pytest.mark.usefixtures("pilot")
async def test_protokol_zbiorczy_nie_daje_sie_pobrac_z_portalu(app_client, texts):  # noqa: F811
    jan = await make_person()
    anna = await make_person()
    await _same_client(anna, jan.client_id)
    message_id = f"cez-{tag()}"
    content = f"%PDF-1.4 cez {message_id}".encode()
    texts[content] = _cez(await _named(jan, "Jan"), await _named(anna, "Anna"))
    reader = FakeMailbox(
        [_message(message_id, f"pm.testowy@{DOMAIN}", "RE: Protokół odbioru")],
        {message_id: [_attachment(NAME, content)]},
    )

    assert (await _read(reader))["created"] == 2
    own_copy = (await _of_contract(jan.contract_id))[0]
    headers = await session_headers(app_client, jan)

    # Kopia przy kontrakcie Jana ma też godziny Anny: bez pliku i bez nazwy.
    response = await app_client.get(
        f"{BASE}/finance/documents/{own_copy.id}/file", headers=headers
    )
    assert response.status_code == 404
    assert content not in response.content
    rows = await _documents(app_client, headers)
    assert [(row["id"], row["downloadable"]) for row in rows] == [(own_copy.id, False)]
    assert rows[0]["file_name"] is None
    assert rows[0]["status"] == "received"


@pytest.mark.usefixtures("pilot")
async def test_plik_wyslany_przez_konsultanta_mailem_da_sie_pobrac(app_client):
    jan = await make_person()
    message_id = f"own-{tag()}"
    content = f"%PDF-1.4 raport {message_id}".encode()
    reader = FakeMailbox(
        [_message(message_id, jan.email.upper(), "Raport wrzesień 2026")],
        {message_id: [_attachment("raport.pdf", content)]},
    )

    assert (await _read(reader))["created"] == 1
    document = (await _of_contract(jan.contract_id))[0]
    headers = await session_headers(app_client, jan)

    response = await app_client.get(
        f"{BASE}/finance/documents/{document.id}/file", headers=headers
    )
    assert response.status_code == 200
    assert response.content == content
    rows = await _documents(app_client, headers)
    assert [(row["file_name"], row["downloadable"]) for row in rows] == [
        ("raport.pdf", True)
    ]
