"""Przedłużenie, którego okres OBEJMUJE dziś, wskrzesza zakończony kontrakt.

Zgłoszenie: „Dodanie przedłużenia do zamówienia z zakładki Zakończone nie
przenosi go do Aktywnych". Diagnoza z ticketu („mechanizm nie jest wywoływany,
gdy zamówienie źródłowe jest w zakładce Zakończone") okazała się trafna co do
skutku, ale nie co do miejsca: nie istniał ŻADEN mechanizm — ``POST
/clients/{id}/orders`` tworzył zamówienie i nie dotykał statusu kontraktu
z żadnej zakładki. Widoczne było to tylko z zakładki „Zakończeni", bo pigułki
czytają ``contract_status``, a kontraktor aktywny i tak już tam był.

Reguła sprawdzana tutaj zależy WYŁĄCZNIE od dat, nie od zakładki źródłowej.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, ContractWorkMode
from app.services.contract_lifecycle import order_period_covers

pytestmark = pytest.mark.asyncio


async def _seed_ended_contract(
    *,
    end_date: date,
    client_order_end_date: date | None = None,
    status: ContractStatus = ContractStatus.ended,
) -> tuple[int, int]:
    """Kontraktor po zakończonym projekcie — wiersz z zakładki „Zakończeni”."""
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Erste Test {suffix}")
        candidate = Candidate(name=f"Mariusz{suffix}", lastname=f"Testowy{suffix}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            work_mode=ContractWorkMode.remote,
            status=status,
            start_date=end_date - timedelta(days=365),
            end_date=end_date,
            rate_candidate=15000,
            rate_client=20000,
            client_order_end_date=client_order_end_date,
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id


async def _contract_state(contract_id: int) -> tuple[ContractStatus, date | None]:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        return contract.status, contract.end_date


async def _client_order_end(contract_id: int) -> date | None:
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        assert contract is not None
        return contract.client_order_end_date


async def _post_extension(
    app_client, headers, client_id: int, contract_id: int, *, start: date, end
):
    data = {
        "contract_id": str(contract_id),
        "title": f"K/2026/{uuid.uuid4().hex[:6]}",
        "start_date": start.isoformat(),
        "order_status": "active",
        "rate_client": "20000",
    }
    if end is not None:
        data["end_date"] = end.isoformat()
    return await app_client.post(
        f"/api/clients/{client_id}/orders", data=data, headers=headers
    )


class TestOrderPeriodCovers:
    """Czysta reguła dat — bez DB, bez HTTP."""

    def test_running_period_covers_today(self):
        today = date(2026, 8, 25)
        assert order_period_covers(date(2026, 7, 1), date(2026, 9, 30), today)

    def test_future_start_does_not_cover(self):
        today = date(2026, 8, 25)
        assert not order_period_covers(date(2026, 9, 1), date(2026, 12, 31), today)

    def test_past_period_does_not_cover(self):
        today = date(2026, 8, 25)
        assert not order_period_covers(date(2026, 1, 1), date(2026, 6, 30), today)

    def test_open_ended_reaches_right_without_bound(self):
        today = date(2026, 8, 25)
        assert order_period_covers(date(2026, 7, 1), None, today)

    def test_boundaries_are_inclusive(self):
        today = date(2026, 8, 25)
        assert order_period_covers(today, today, today)

    def test_missing_start_is_not_assumed_to_have_begun(self):
        """Puste pole nie jest dowodem, że współpraca trwa."""
        assert not order_period_covers(None, date(2026, 12, 31), date(2026, 8, 25))


async def test_running_extension_moves_contractor_back_to_active(
    app_client, app_auth_headers
):
    """Scenariusz (a) z ticketu — przedłużenie trwające dziś."""
    today = date.today()
    client_id, contract_id = await _seed_ended_contract(
        end_date=today - timedelta(days=60)
    )
    new_end = today + timedelta(days=36)

    resp = await _post_extension(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        start=today - timedelta(days=25),
        end=new_end,
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.active
    # Data końca musi iść za zamówieniem — inaczej nocny `_promote_statuses`
    # zdemotuje wskrzeszony kontrakt z powrotem tej samej nocy.
    assert end_date == new_end


async def test_future_extension_leaves_the_contract_alone(
    app_client, app_auth_headers
):
    """Scenariusz (b) — przedłużenie zaczynające się w przyszłości."""
    today = date.today()
    previous_end = today - timedelta(days=60)
    client_id, contract_id = await _seed_ended_contract(end_date=previous_end)

    resp = await _post_extension(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        start=today + timedelta(days=30),
        end=today + timedelta(days=120),
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.ended
    assert end_date == previous_end


async def test_open_ended_running_extension_makes_the_contract_indefinite(
    app_client, app_auth_headers
):
    today = date.today()
    client_id, contract_id = await _seed_ended_contract(
        end_date=today - timedelta(days=10),
        client_order_end_date=today - timedelta(days=10),
    )

    resp = await _post_extension(
        app_client,
        app_auth_headers,
        client_id,
        contract_id,
        start=today,
        end=None,
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.active
    assert end_date is None
    # „Koniec zamówienia u klienta" z PRZESZŁĄ datą na umowie bezterminowej
    # przestał cokolwiek opisywać: profil kontraktu pokazałby go obok „Okres:
    # … – bezterminowo". Alert `_client_orders_ending` tego NIE zgłosi
    # (wymaga `>= today`), więc rozjazd byłby całkowicie niemy. Migracja 0243
    # zeruje tę kolumnę dla wierszy historycznych — runtime musi robić to samo.
    assert await _client_order_end(contract_id) is None


async def test_running_extension_moves_the_tracked_client_order_end(
    app_client, app_auth_headers
):
    """Śledzony „Koniec zamówienia u klienta" idzie za nowym horyzontem…"""
    today = date.today()
    client_id, contract_id = await _seed_ended_contract(
        end_date=today - timedelta(days=60),
        client_order_end_date=today - timedelta(days=60),
    )
    new_end = today + timedelta(days=36)
    resp = await _post_extension(
        app_client, app_auth_headers, client_id, contract_id,
        start=today - timedelta(days=25), end=new_end,
    )
    assert resp.status_code == 201, resp.text
    assert await _client_order_end(contract_id) == new_end


async def test_untracked_client_order_end_is_not_invented(
    app_client, app_auth_headers
):
    """…ale NULL zostaje NULL-em — nie wymyślamy daty, której nikt nie śledził.

    Lustro `_synced_client_order_end` (ta sama reguła co przy aneksie
    i `/bulk-extend`).
    """
    today = date.today()
    client_id, contract_id = await _seed_ended_contract(
        end_date=today - timedelta(days=60), client_order_end_date=None
    )
    resp = await _post_extension(
        app_client, app_auth_headers, client_id, contract_id,
        start=today - timedelta(days=25), end=today + timedelta(days=36),
    )
    assert resp.status_code == 201, resp.text
    assert await _client_order_end(contract_id) is None


async def test_draft_extension_is_not_evidence_of_running_work(
    app_client, app_auth_headers
):
    """Szkic nie jest zobowiązaniem — nie wolno nim wskrzeszać kontraktu."""
    today = date.today()
    previous_end = today - timedelta(days=60)
    client_id, contract_id = await _seed_ended_contract(end_date=previous_end)

    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data={
            "contract_id": str(contract_id),
            "title": "(bez numeru)",
            "start_date": (today - timedelta(days=5)).isoformat(),
            "end_date": (today + timedelta(days=30)).isoformat(),
            "order_status": "draft",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.ended
    assert end_date == previous_end


async def test_void_contract_is_never_touched_by_an_order(
    app_client, app_auth_headers
):
    """``void`` jest TERMINALNY — zamówienie nie przesuwa daty umowy unieważnionej.

    ``create_order_extension`` nie filtruje statusu kontraktu, więc zamówienie
    da się dopiąć także do soft-skasowanej umowy. Bez bramki wskrzeszenie po
    cichu zmieniałoby jej `end_date` — a `ALLOWED_TRANSITIONS[void]` jest
    pustym zbiorem właśnie dlatego, że z tego stanu nie ma wyjścia.
    """
    today = date.today()
    previous_end = today - timedelta(days=60)
    client_id, contract_id = await _seed_ended_contract(
        end_date=previous_end, status=ContractStatus.void
    )

    resp = await _post_extension(
        app_client, app_auth_headers, client_id, contract_id,
        start=today - timedelta(days=5), end=today + timedelta(days=90),
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.void
    assert end_date == previous_end


async def test_draft_contract_is_not_activated_through_an_order(
    app_client, app_auth_headers
):
    """Szkic ma WŁASNY walidowany cykl życia — nie wchodzi się w przychód bokiem."""
    today = date.today()
    previous_end = today - timedelta(days=60)
    client_id, contract_id = await _seed_ended_contract(
        end_date=previous_end, status=ContractStatus.draft
    )

    resp = await _post_extension(
        app_client, app_auth_headers, client_id, contract_id,
        start=today - timedelta(days=5), end=today + timedelta(days=90),
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.draft
    assert end_date == previous_end


async def test_active_contract_horizon_is_left_alone(app_client, app_auth_headers):
    """Zamówienie NIE rozciąga horyzontu umowy, która i tak obowiązuje.

    Przed tą zmianą dodanie zamówienia nie ruszało `end_date` aktywnej umowy
    i nikt o to nie prosił — rozszerzenie tego „przy okazji" byłoby zmianą
    zachowania poza zakresem ticketu.
    """
    today = date.today()
    contract_end = today + timedelta(days=10)
    client_id, contract_id = await _seed_ended_contract(
        end_date=contract_end, status=ContractStatus.active
    )

    resp = await _post_extension(
        app_client, app_auth_headers, client_id, contract_id,
        start=today, end=today + timedelta(days=180),
    )
    assert resp.status_code == 201, resp.text

    status, end_date = await _contract_state(contract_id)
    assert status == ContractStatus.active
    assert end_date == contract_end
