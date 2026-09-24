"""Audyt 24.09.2026, blok A: zamówienia MD, zamiany/przejęcia, import zużycia.

Każdy test odtwarza jeden defekt z raportu (W1–W5, S1–S3, S9, N1): stan,
w którym te same MD liczyły się dwa razy, znikały bez śladu albo trafiały na
zamówienie, które ich nie przyjmowało. Nazwiska i numery są zmyślone (repo
jest publiczne); daty liczone od ``business_today()``, bez stałych lat.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today
from tests.test_md_import_duplicate_consultant_rows import (
    _create_group,
    _enable_multi,
    _extend,
    _finance_headers,
    _md_line,
    _seed_client_with_contracts,
    _sheet,
)
from tests.test_order_line_takeover import _seed as _seed_takeover
from tests.test_order_line_takeover import _takeover_url

pytestmark = pytest.mark.asyncio


def _period() -> str:
    return business_today().strftime("%Y-%m")


def _next_month_first() -> date:
    today = business_today()
    return (date(today.year, today.month, 1) + timedelta(days=32)).replace(day=1)


async def _import(
    app_client: AsyncClient, headers: dict, payload: bytes, period: str
) -> dict:
    resp = await app_client.post(
        "/api/md-consumption/imports",
        files={
            "file": (
                "raport.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"period_month": period},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _entries(order_id: int) -> dict[str, tuple[Decimal, str]]:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import ClientOrderMdConsumption

    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            select(
                ClientOrderMdConsumption.period_month,
                ClientOrderMdConsumption.md_reported,
                ClientOrderMdConsumption.source,
            ).where(ClientOrderMdConsumption.order_id == order_id)
        )
        return {
            month: (Decimal(str(md)).normalize(), source) for month, md, source in rows
        }


async def _add_manual_entry(order_id: int, period: str, md: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.md_consumption import (
        CONSUMPTION_SOURCE_MANUAL,
        ClientOrderMdConsumption,
    )

    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrderMdConsumption(
                order_id=order_id,
                period_month=period,
                md_reported=Decimal(md),
                source=CONSUMPTION_SOURCE_MANUAL,
            )
        )
        await db.commit()


async def _transfer_events(group_id: int) -> list[dict]:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroupEvent

    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(ClientOrderGroupEvent).where(
                ClientOrderGroupEvent.group_id == group_id,
                ClientOrderGroupEvent.event_type == "transfer_md",
            )
        )
        return [dict(event.payload or {}) for event in rows]


async def _line_row(line_id: int):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    async with AsyncSessionLocal() as db:
        return await db.get(ClientOrder, line_id)


# ── W1: zamiana z przyszłą datą + koniec umowy odchodzącego ─────────────────


async def test_contract_end_after_a_future_swap_opens_no_md_case(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Pula odchodzącego przeszła na następcę przy zamianie — zakończenie jego
    umowy nie zakłada sprawy MD, która rozdałaby te same MD drugi raz."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrderStatus
    from app.models.client_order_offboarding import ClientOrderOffboardingCase
    from app.services.contract_order_offboarding import (
        apply_contract_order_offboarding,
    )

    seed = await _seed_takeover(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    swap_on = business_today() + timedelta(days=5)
    swapped = await app_client.post(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/lines/{seed['line_id']}/swap",
        json={
            "contract_id": seed["kamila_contract_id"],
            "rate_cost": 680,
            "rate_revenue": 800,
            "swap_date": swap_on.isoformat(),
            "md_transfer_method": "one_to_one",
        },
        headers=app_auth_headers,
    )
    assert swapped.status_code == 201, swapped.text
    assert (await _line_row(seed["line_id"])).status == ClientOrderStatus.active

    async with AsyncSessionLocal() as db:
        result = await apply_contract_order_offboarding(
            db,
            contract_id=seed["konrad_contract_id"],
            effective_date=seed["departure"],
            today=seed["departure"] + timedelta(days=1),
        )
        await db.commit()
        cases = (
            await db.scalars(
                select(ClientOrderOffboardingCase).where(
                    ClientOrderOffboardingCase.order_id == seed["line_id"]
                )
            )
        ).all()

    assert result.md_cases_created == 0
    assert cases == []
    assert (await _line_row(seed["line_id"])).status == ClientOrderStatus.completed


async def test_md_decision_is_refused_for_a_line_with_a_swap_successor(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Sprawa sprzed poprawki: decyzja o puli, która jest już budżetem
    następcy z zamiany, kończy się 409 i nie zmienia niczego."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroupEvent
    from app.models.contract import RateUnit
    from app.models.order_type import OrderType

    seed = await _seed_takeover()
    _enable_multi(monkeypatch, seed["client_id"])
    async with AsyncSessionLocal() as db:
        successor = ClientOrder(
            client_id=seed["client_id"],
            contract_id=seed["kamila_contract_id"],
            order_group_id=seed["group_id"],
            order_type=OrderType.md,
            title="Zamówienie — Kamila",
            status=ClientOrderStatus.active,
            start_date=seed["departure"] + timedelta(days=1),
            md_rate_cost=Decimal("680.00"),
            md_rate_revenue=Decimal("800.00"),
            rate_unit=RateUnit.daily,
            billing_hours_per_month=168,
            currency="PLN",
            rate_client_currency="PLN",
            rate_candidate_currency="PLN",
            md_input_mode="md",
            md_input_value=Decimal("187"),
            md_total=Decimal("187"),
            md_remaining=Decimal("187"),
            md_manual_adjustment=Decimal("0"),
            predecessor_order_id=seed["line_id"],
        )
        db.add(successor)
        await db.flush()
        db.add(
            ClientOrderGroupEvent(
                group_id=seed["group_id"],
                order_id=successor.id,
                event_type="zamiana_kontraktora",
                description="Zamiana kontraktora",
                payload={"old_order_id": seed["line_id"]},
            )
        )
        await db.commit()

    resp = await app_client.post(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/offboarding-cases/{seed['case_id']}/resolve",
        json={"action": "remove", "expected_version": 1},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "następcę" in resp.text
    line = await _line_row(seed["line_id"])
    assert Decimal(str(line.md_total)) == Decimal("190")


# ── W2–W4: import MD a poprzednik / następca ────────────────────────────────


async def test_import_does_not_redirect_onto_a_manual_predecessor_entry(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """W2: ręczny wpis DL na poprzedniku za ten miesiąc nie jest śladem
    podziału — wiersz następcy zostaje na następcy, ręczny wpis nietknięty."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.client_order_group import ClientOrderGroup

    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 20)]
    )
    successor_start = business_today() - timedelta(days=5)
    successor = await _extend(
        app_client,
        app_auth_headers,
        client_id,
        group["id"],
        start=successor_start,
        lines=[
            dict(_md_line(contracts[0], 50), start_date=successor_start.isoformat())
        ],
    )
    old_line = group["lines"][0]["id"]
    new_line = successor["lines"][0]["id"]
    # Następca już obowiązuje, poprzednik zakończony dzień przed jego startem.
    async with AsyncSessionLocal() as db:
        (await db.get(ClientOrderGroup, successor["id"])).status = "active"
        (await db.get(ClientOrder, new_line)).status = ClientOrderStatus.active
        previous = await db.get(ClientOrderGroup, group["id"])
        previous.status = "completed"
        previous.closure_date = successor_start - timedelta(days=1)
        line = await db.get(ClientOrder, old_line)
        line.status = ClientOrderStatus.completed
        line.end_date = successor_start - timedelta(days=1)
        await db.commit()
    await _add_manual_entry(old_line, _period(), "7")

    finance = await _finance_headers(app_client)
    await _import(app_client, finance, _sheet([(names[0], 30)]), _period())

    assert (await _entries(old_line))[_period()] == (Decimal("7"), "manual")
    assert (await _entries(new_line))[_period()] == (Decimal("30"), "import")


async def test_assigning_to_predecessor_keeps_the_successors_own_entry(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """W3: własny (ręczny) wpis następcy za miesiąc nie jest przeniesieniem —
    rozliczenie poprzednika go nie zeruje ani nie nadpisuje nadwyżką."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 20)]
    )
    successor_start = business_today()
    successor = await _extend(
        app_client,
        app_auth_headers,
        client_id,
        group["id"],
        start=successor_start,
        lines=[
            dict(_md_line(contracts[0], 50), start_date=successor_start.isoformat())
        ],
    )
    old_line = group["lines"][0]["id"]
    new_line = successor["lines"][0]["id"]
    await _add_manual_entry(new_line, _period(), "4")

    finance = await _finance_headers(app_client)
    await _import(app_client, finance, _sheet([(names[0], 15)]), _period())

    assert (await _entries(old_line))[_period()] == (Decimal("15"), "import")
    assert (await _entries(new_line))[_period()] == (Decimal("4"), "manual")

    # Nadwyżka też nie nadpisuje własnego wpisu — zostaje na poprzedniku.
    await _import(app_client, finance, _sheet([(names[0], 30)]), _period())
    assert (await _entries(old_line))[_period()] == (Decimal("30"), "import")
    assert (await _entries(new_line))[_period()] == (Decimal("4"), "manual")
    assert await _transfer_events(successor["id"]) == []


async def test_overflow_does_not_go_to_a_successor_that_starts_later(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """W4: następca zaczyna się w przyszłym miesiącu — nie rozlicza miesiąca
    raportu, więc nadwyżka zostaje widoczna jako przekroczenie poprzednika."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 20)]
    )
    successor_start = _next_month_first()
    successor = await _extend(
        app_client,
        app_auth_headers,
        client_id,
        group["id"],
        start=successor_start,
        lines=[
            dict(_md_line(contracts[0], 50), start_date=successor_start.isoformat())
        ],
    )
    old_line = group["lines"][0]["id"]
    new_line = successor["lines"][0]["id"]

    finance = await _finance_headers(app_client)
    await _import(app_client, finance, _sheet([(names[0], 30)]), _period())

    assert (await _entries(old_line))[_period()] == (Decimal("30"), "import")
    assert await _entries(new_line) == {}
    assert await _transfer_events(successor["id"]) == []
    line = await _line_row(old_line)
    assert Decimal(str(line.md_remaining)) == Decimal("-10")


# ── W5: linia z przeniesioną pulą nie znika bez śladu ───────────────────────


async def test_deleting_a_line_that_received_a_transferred_pool_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    seed = await _seed_takeover()
    _enable_multi(monkeypatch, seed["client_id"])
    taken = await app_client.post(
        _takeover_url(seed),
        json={
            "contract_id": seed["kamila_contract_id"],
            "departing_order_id": seed["line_id"],
            "entry_date": (seed["departure"] + timedelta(days=1)).isoformat(),
            "rate_cost": 680,
            "rate_revenue": 800,
            "expected_case_version": 1,
        },
        headers=app_auth_headers,
    )
    assert taken.status_code == 201, taken.text
    target_id = taken.json()["id"]

    resp = await app_client.delete(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"
        f"/lines/{target_id}",
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "przeniesiono pozostałe MD" in resp.text
    assert await _line_row(target_id) is not None


# ── S1: walidacja zamiany kontraktora ───────────────────────────────────────


async def test_swap_after_the_line_end_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from tests.test_multi_consultant_orders import (
        _create_group as _create_mc_group,
        _enable_for,
        _line_payload,
        _seed_client_with_contracts as _seed_mc,
    )

    client_id, contracts, _ = await _seed_mc(2)
    _enable_for(monkeypatch, client_id)
    line_end = business_today() + timedelta(days=10)
    group = await _create_mc_group(
        app_client,
        app_auth_headers,
        client_id,
        [_line_payload(contracts[0], end_date=line_end.isoformat())],
    )
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{group['lines'][0]['id']}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": (line_end + timedelta(days=1)).isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "po końcu" in resp.text


async def test_swap_to_a_person_already_on_the_order_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus
    from tests.test_multi_consultant_orders import (
        _create_group as _create_mc_group,
        _enable_for,
        _line_payload,
        _seed_client_with_contracts as _seed_mc,
    )

    client_id, contracts, _ = await _seed_mc(2)
    _enable_for(monkeypatch, client_id)
    group = await _create_mc_group(
        app_client,
        app_auth_headers,
        client_id,
        [_line_payload(contracts[0]), _line_payload(contracts[1])],
    )
    # Druga umowa osoby, która już pracuje na tym zamówieniu.
    async with AsyncSessionLocal() as db:
        existing = await db.get(Contract, contracts[1])
        twin = Contract(
            candidate_id=existing.candidate_id,
            client_id=client_id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=5),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(twin)
        await db.commit()
        twin_id = twin.id

    old_line = next(
        line["id"] for line in group["lines"] if line["contract_id"] == contracts[0]
    )
    url = f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{old_line}/swap"
    body = {
        "rate_cost": 800,
        "rate_revenue": 950,
        "swap_date": business_today().isoformat(),
    }
    same_contract = await app_client.post(
        url, json={**body, "contract_id": contracts[1]}, headers=app_auth_headers
    )
    assert same_contract.status_code == 409, same_contract.text
    same_person = await app_client.post(
        url, json={**body, "contract_id": twin_id}, headers=app_auth_headers
    )
    assert same_person.status_code == 409, same_person.text


# ── S2: zaplanowane zastępstwo a zakończenie zamówienia ─────────────────────


async def _schedule_takeover(app_client, headers, seed, entry: date) -> int:
    resp = await app_client.post(
        _takeover_url(seed),
        json={
            "contract_id": seed["kamila_contract_id"],
            "departing_order_id": seed["line_id"],
            "entry_date": entry.isoformat(),
            "rate_cost": 680,
            "rate_revenue": 800,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "draft"
    return resp.json()["id"]


async def test_closing_the_order_cancels_a_takeover_that_cannot_enter(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zakończenie z dniem dzisiejszym: zastępstwo od jutra nie wejdzie —
    jest anulowane z wpisem, a „Przywróć” nie oddaje go jako aktywnej linii."""
    from app.models.client_order import ClientOrderStatus

    seed = await _seed_takeover(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    planned = await _schedule_takeover(
        app_client, app_auth_headers, seed, seed["departure"] + timedelta(days=1)
    )
    base = f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}"

    closed = await app_client.post(
        f"{base}/close",
        json={"closure_date": business_today().isoformat()},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    assert (await _line_row(planned)).status == ClientOrderStatus.cancelled

    events = await app_client.get(f"{base}/events", headers=app_auth_headers)
    assert any(
        "Zaplanowane zastępstwo" in e["description"] and "anulowane" in e["description"]
        for e in events.json()["events"]
    )

    reopened = await app_client.post(f"{base}/reopen", headers=app_auth_headers)
    assert reopened.status_code == 200, reopened.text
    assert (await _line_row(planned)).status == ClientOrderStatus.cancelled


async def test_takeover_enters_an_order_completed_with_a_later_date(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zakończenie z datą PO dniu wejścia: zastępstwo zostaje i wchodzi
    w swoim dniu, mimo że zamówienie ma już status „zakończone"."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrderStatus
    from app.services.contract_order_offboarding import (
        apply_contract_order_offboarding,
    )
    from app.services.order_line_takeover import activate_due_takeovers

    seed = await _seed_takeover(source_state="leaving")
    _enable_multi(monkeypatch, seed["client_id"])
    entry = seed["departure"] + timedelta(days=1)
    planned = await _schedule_takeover(app_client, app_auth_headers, seed, entry)
    closed = await app_client.post(
        f"/api/clients/{seed['client_id']}/order-groups/{seed['group_id']}/close",
        json={"closure_date": (entry + timedelta(days=30)).isoformat()},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    assert (await _line_row(planned)).status == ClientOrderStatus.draft

    async with AsyncSessionLocal() as db:
        await apply_contract_order_offboarding(
            db,
            contract_id=seed["konrad_contract_id"],
            effective_date=seed["departure"],
            today=entry,
        )
        activated = await activate_due_takeovers(db, today=entry)
        await db.commit()

    assert activated == 1
    assert (await _line_row(planned)).status == ClientOrderStatus.active


# ── S9: numer zamówienia ────────────────────────────────────────────────────


async def test_second_open_order_with_the_same_number_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    other_id, other_contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id, other_id)
    number = f"4500{uuid.uuid4().int % 10**6:06d}"

    def body(contract_id: int, value: str) -> dict:
        return {
            "order_number": value,
            "start_date": (business_today() - timedelta(days=10)).isoformat(),
            "lines": [_md_line(contract_id, 20)],
        }

    first = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json=body(contracts[0], number),
        headers=app_auth_headers,
    )
    assert first.status_code == 201, first.text
    duplicate = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json=body(contracts[1], f" {number} "),
        headers=app_auth_headers,
    )
    assert duplicate.status_code == 409, duplicate.text
    assert number in duplicate.text
    # Inny klient może mieć ten sam numer.
    elsewhere = await app_client.post(
        f"/api/clients/{other_id}/order-groups",
        json=body(other_contracts[0], number),
        headers=app_auth_headers,
    )
    assert elsewhere.status_code == 201, elsewhere.text


# ── N1: zakończone zamówienie wyczerpane ────────────────────────────────────


async def test_reopening_an_order_closed_while_exhausted_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroup

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0], 20)]
    )
    async with AsyncSessionLocal() as db:
        (await db.get(ClientOrderGroup, group["id"])).status = "exhausted"
        await db.commit()
    base = f"/api/clients/{client_id}/order-groups/{group['id']}"

    closed = await app_client.post(
        f"{base}/close",
        json={"closure_date": business_today().isoformat()},
        headers=app_auth_headers,
    )
    assert closed.status_code == 200, closed.text
    reopened = await app_client.post(f"{base}/reopen", headers=app_auth_headers)
    assert reopened.status_code == 409, reopened.text
    assert "wyczerpaną pulę" in reopened.text


# ── S5: plik korygujący wspólnej puli MD ────────────────────────────────────


async def test_correction_file_keeps_the_md_of_people_it_does_not_mention(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Pierwszy plik: A 10 MD + B 5 MD. Korekta za ten sam miesiąc niesie
    tylko A (12 MD) — suma miesiąca to 12 + 5, nie same 12."""
    from tests.test_md_import_shared_budget import (
        _enable_cyfrowy_polsat,
        _group_from_list,
    )
    from tests.test_order_lifecycle_and_cost import (
        _cost_line,
        _create_group as _create_lifecycle_group,
        _finance_headers as _lifecycle_finance_headers,
        _import_sheet,
        _seed_client_with_contracts as _seed_lifecycle,
        _sheet as _notes_sheet,
    )

    client_id, contracts, names = await _seed_lifecycle(2)
    _enable_cyfrowy_polsat(monkeypatch, client_id)
    number = f"45008{uuid.uuid4().int % 10**5:05d}"
    group = await _create_lifecycle_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0]), _cost_line(contracts[1])],
        order_number=number,
        is_md_budget_based=True,
        md_budget_total=50,
    )
    finance = await _lifecycle_finance_headers(app_client)

    first = await _import_sheet(
        app_client,
        finance,
        _notes_sheet(
            [(names[0], 10, f"SAP {number}", 0), (names[1], 5, f"SAP {number}", 0)]
        ),
    )
    assert first["rows_applied"] == 2, first
    correction = await _import_sheet(
        app_client, finance, _notes_sheet([(names[0], 12, f"SAP {number}", 0)])
    )
    assert correction["rows_applied"] == 1, correction

    body = await _group_from_list(app_client, app_auth_headers, client_id, group["id"])
    assert body["md_budget_used"] == pytest.approx(17.0)
    assert body["md_budget_remaining"] == pytest.approx(33.0)
    events = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group['id']}/events",
        headers=app_auth_headers,
    )
    assert any(
        "nieobecnych w tym pliku" in e["description"] and names[1] in e["description"]
        for e in events.json()["events"]
    )
