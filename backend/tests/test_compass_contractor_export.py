"""Eksport kontraktorów dla COMPASSA: co jedzie, czego nie ma i kto jest na ławce.

Rok fixture'ów (2039) CELOWO nieużywany przez inne pliki — baza testowa jest
wspólna dla przebiegu i nie jest czyszczona, więc rok zajęty przez sąsiada
wraca jako „regresja" w kodzie, którego nikt nie ruszał.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus

EXPORT = "/api/integrations/compass/contractors"


async def _key(app_client: AsyncClient, headers: dict) -> str:
    """Klucz wydany tymi samymi helperami co w `test_service_accounts`.

    Własna kopia tworzenia konta rozjeżdżałaby się z kontraktem API przy
    pierwszej zmianie schematu (i już raz to zrobiła — pole nazywa się
    `label`, nie `name`).
    """
    from tests.test_service_accounts import _account_with_key

    _, api_key, _ = await _account_with_key(app_client, headers, ["contractors:read"])
    return api_key


async def _seed_contract(db, *, with_current_order: bool, tag: str):
    u = f"{tag}-{uuid.uuid4().hex[:8]}"
    client = Client(name=f"Bench Client {u}")
    cand = Candidate(name="Ben", lastname=f"CZ-{u}", email=f"ben-{u}@example.com")
    db.add_all([client, cand])
    await db.flush()

    contract = Contract(
        candidate_id=cand.id,
        client_id=client.id,
        status=ContractStatus.active,
        start_date=date(2039, 1, 1),
    )
    db.add(contract)
    await db.flush()

    if with_current_order:
        today = business_today()
        db.add(
            ClientOrder(
                contract_id=contract.id,
                client_id=client.id,
                title=f"Zamówienie {u}",
                status=ClientOrderStatus.active,
                start_date=today - timedelta(days=10),
                end_date=today + timedelta(days=10),
            )
        )
    await db.commit()
    return {"contract_id": contract.id, "candidate_id": cand.id}


async def _fetch_all(app_client: AsyncClient, api_key: str) -> dict[int, dict]:
    """Eksport jest stronicowany — test musi przejść wszystkie strony.

    Baza testowa jest wspólna, więc świeżo zasiany kontrakt nie musi zmieścić
    się na pierwszej stronie. Czytanie tylko jej dawałoby test, który zaczyna
    padać, gdy ktoś dołoży dane w sąsiednim pliku.
    """
    out: dict[int, dict] = {}
    page = 1
    while True:
        r = await app_client.get(
            EXPORT,
            headers={"X-API-Key": api_key},
            params={"page": page, "page_size": 500},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        for item in body["items"]:
            out[item["nexus_contract_id"]] = item
        if not body["has_more"]:
            return out
        page += 1


async def test_bench_signal_separates_staffed_from_unstaffed(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`lacks_current_order` to odpowiednik `contractor_bench` w COMPASSIE.

    Sygnał jest WYPROWADZANY z zamówień, nie deklarowany — dzięki temu obejmuje
    też kontraktorów, których umowy nie generowano w NEXUSIE (tych `suspended`
    by nie złapał).
    """
    async with AsyncSessionLocal() as db:
        staffed = await _seed_contract(db, with_current_order=True, tag="staffed")
        bench = await _seed_contract(db, with_current_order=False, tag="bench")

    api_key = await _key(app_client, app_auth_headers)
    rows = await _fetch_all(app_client, api_key)

    assert rows[staffed["contract_id"]]["lacks_current_order"] is False
    assert rows[bench["contract_id"]]["lacks_current_order"] is True


async def test_export_carries_the_email_that_compass_is_missing(
    app_client: AsyncClient, app_auth_headers: dict
):
    """E-mail jest POWODEM istnienia tego eksportu.

    COMPASS ma 689 kontraktorów i zero e-maili, więc łączy ich po nazwisku.
    Bez tego pola cała integracja tożsamości nie ma się o co oprzeć.
    """
    async with AsyncSessionLocal() as db:
        seeded = await _seed_contract(db, with_current_order=True, tag="email")

    api_key = await _key(app_client, app_auth_headers)
    rows = await _fetch_all(app_client, api_key)
    assert "@" in (rows[seeded["contract_id"]]["candidate"]["email"] or "")
