"""Eksport kontraktorów dla COMPASSA: co jedzie, czego nie ma i kto jest na ławce.

Rok fixture'ów (2039) CELOWO nieużywany przez inne pliki — baza testowa jest
wspólna dla przebiegu i nie jest czyszczona, więc rok zajęty przez sąsiada
wraca jako „regresja" w kodzie, którego nikt nie ruszał.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

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


async def test_paging_survives_an_edit_between_pages(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Edycja kontraktu między stronami nie gubi ani nie dubluje wierszy.

    COMPASS czyta eksport strona po stronie w jednym biegu. Przy sortowaniu po
    `updated_at` kontrakt poprawiony w trakcie biegu skakał na pierwszą stronę:
    sam wypadał z eksportu, a ostatni wiersz pierwszej strony przychodził drugi
    raz. Odbiorca zapisywał wtedy „brak w NEXUS" osobie, która w nim jest.
    """
    from sqlalchemy import update

    async with AsyncSessionLocal() as db:
        for i in range(3):
            await _seed_contract(db, with_current_order=False, tag=f"paging{i}")

    api_key = await _key(app_client, app_auth_headers)
    everyone = set(await _fetch_all(app_client, api_key))
    page_size = max(1, len(everyone) // 2)

    async def _page(page: int) -> dict:
        r = await app_client.get(
            EXPORT,
            headers={"X-API-Key": api_key},
            params={"page": page, "page_size": page_size},
        )
        assert r.status_code == 200, r.text
        return r.json()

    first = await _page(1)
    seen = [item["nexus_contract_id"] for item in first["items"]]
    later = sorted(everyone - set(seen))
    assert later, "test potrzebuje kontraktu spoza pierwszej strony"

    # Kontrakt z dalszej strony zostaje „poprawiony" w trakcie biegu.
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Contract)
            .where(Contract.id == later[-1])
            .values(updated_at=datetime.now(timezone.utc) + timedelta(days=3650))
        )
        await db.commit()

    page, body = 1, first
    while body["has_more"]:
        page += 1
        body = await _page(page)
        seen.extend(item["nexus_contract_id"] for item in body["items"])

    assert len(seen) == len(set(seen)), "wiersz przyszedł dwa razy"
    assert set(seen) == everyone, "wiersz wypadł z eksportu"
