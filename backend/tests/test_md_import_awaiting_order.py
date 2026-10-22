"""Import MD: wiersz bez numeru zamówienia czeka na kolejne zamówienie (21.10.2026).

Arkusz BIK za wrzesień: ta sama osoba w dwóch wierszach — 11,625 MD z numerem
zamówienia i 12,25 MD bez numeru (kolejne zamówienie jeszcze nie wpłynęło).
Do tej poprawki import sumował oba wiersze (23,875 MD) na zamówienie z numerem
i oznaczał oba jako „Do weryfikacji – przekroczenie puli o 12,25 MD”.

Teraz wiersz z numerem schodzi sam, wiersz bez numeru dostaje „Oczekuje na
zamówienie”, a jego MD schodzą z kolejnego zamówienia tej osoby, gdy pojawi
się w NEXUSIE. Nazwiska, numery i liczby są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today
from tests.test_md_import_order_number_assignment import (
    _consumptions,
    _create_group,
    _enable_multi,
    _events,
    _finance_headers,
    _group,
    _import,
    _number,
    _old_start,
    _period,
    _seed,
    _sheet,
)

pytestmark = pytest.mark.asyncio


def _later_start() -> date:
    """Kolejne zamówienie wpływa po miesiącu raportu."""
    today = business_today()
    return date(today.year, today.month, 1)


async def _case(app_client, headers, monkeypatch, *, md_total: float = 15):
    client_id, contract_id, name = await _seed()
    _enable_multi(monkeypatch, client_id)
    number = _number()
    group = await _create_group(
        app_client,
        headers,
        client_id,
        contract_id,
        number=number,
        start=_old_start(),
        end=None,
        md_total=md_total,
    )
    return {
        "client_id": client_id,
        "contract_id": contract_id,
        "name": name,
        "number": number,
        "group": group,
        "line": group["lines"][0]["id"],
    }


async def _next_order(app_client, headers, case, *, md_total: float) -> dict:
    return await _create_group(
        app_client,
        headers,
        case["client_id"],
        case["contract_id"],
        number=_number(),
        start=_later_start(),
        end=None,
        md_total=md_total,
    )


def _split_sheet(case, *, numbered: float = 11.625, awaiting: float = 12.25):
    return _sheet(
        [
            (case["name"], numbered, case["number"], 0),
            (case["name"], awaiting, "", 0),
        ]
    )


def _rows_by_status(detail: dict) -> dict[str, dict]:
    return {row["status"]: row for row in detail["rows"]}


async def _card_line(app_client, headers, case, group_id: int, line_id: int) -> dict:
    group = await _group(app_client, headers, case["client_id"], group_id)
    return next(line for line in group["lines"] if line["id"] == line_id)


async def test_row_without_number_waits_instead_of_merging(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    case = await _case(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)

    detail = await _import(app_client, finance, _split_sheet(case))

    rows = _rows_by_status(detail)
    assert set(rows) == {"applied", "awaiting_order"}, detail["rows"]
    numbered, awaiting = rows["applied"], rows["awaiting_order"]
    # Wymaganie 2 i 7: z zamówienia schodzi tylko wiersz z numerem, bez przekroczenia.
    assert numbered["matched_order_id"] == case["line"]
    assert numbered["overflow_md"] is None
    assert numbered["merged_rows"] == 1
    assert numbered["awaiting_md"] == 12.25
    # Wymaganie 3: wiersz bez numeru nie schodzi z żadnej puli.
    assert awaiting["status_label"] == "Oczekuje na zamówienie"
    assert awaiting["matched_order_id"] is None
    assert awaiting["md_pending"] == 12.25
    assert awaiting["awaiting_md"] == 12.25
    assert awaiting["awaiting_order"]["order_number"] == case["number"]
    assert await _consumptions(case["line"]) == {_period(): Decimal("11.625")}
    # Wymaganie 4: informacja na karcie zamówienia.
    line = await _card_line(
        app_client, app_auth_headers, case, case["group"]["id"], case["line"]
    )
    assert line["md_remaining"] == 3.375
    assert line["awaiting_md"] == [{"period_month": _period(), "md": 12.25}]


async def test_overflow_is_reported_only_for_the_numbered_row(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wymaganie 7: przekroczenie liczy się z samego wiersza z numerem."""
    case = await _case(app_client, app_auth_headers, monkeypatch, md_total=10)
    finance = await _finance_headers(app_client)

    detail = await _import(app_client, finance, _split_sheet(case))

    rows = _rows_by_status(detail)
    assert set(rows) == {"overflow", "awaiting_order"}, detail["rows"]
    assert rows["overflow"]["overflow_md"] == 1.625
    assert rows["awaiting_order"]["md_pending"] == 12.25


async def test_next_order_takes_the_awaiting_md_for_their_month(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wymaganie 5: nowe zamówienie tej osoby — MD schodzą za wrzesień."""
    case = await _case(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)
    detail = await _import(app_client, finance, _split_sheet(case))

    successor = await _next_order(app_client, app_auth_headers, case, md_total=20)
    new_line = successor["lines"][0]["id"]

    assert await _consumptions(new_line) == {_period(): Decimal("12.25")}
    assert await _consumptions(case["line"]) == {_period(): Decimal("11.625")}
    after = await app_client.get(
        f"/api/md-consumption/imports/{detail['id']}", headers=finance
    )
    assert after.status_code == 200, after.text
    rows = after.json()["rows"]
    assert {row["status"] for row in rows} == {"applied"}
    settled = next(row for row in rows if row["order_number_hint"] is None)
    assert settled["matched_order_id"] == new_line
    assert settled["md_pending"] == 0
    # Informacja przy poprzednim zamówieniu znika.
    old = await _card_line(
        app_client, app_auth_headers, case, case["group"]["id"], case["line"]
    )
    assert old["awaiting_md"] == []
    new = await _card_line(
        app_client, app_auth_headers, case, successor["id"], new_line
    )
    assert new["md_remaining"] == 7.75
    assert any(
        "oczekiwały na kolejne zamówienie" in description
        for _, description in await _events(successor["id"])
    )


async def test_awaiting_md_beyond_the_new_pool_keep_waiting(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wymaganie 6: z nowego zamówienia schodzi tyle, ile mieści pula."""
    case = await _case(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)
    await _import(app_client, finance, _split_sheet(case))

    small = await _next_order(app_client, app_auth_headers, case, md_total=5)
    small_line = small["lines"][0]["id"]
    assert await _consumptions(small_line) == {_period(): Decimal("5")}
    old = await _card_line(
        app_client, app_auth_headers, case, case["group"]["id"], case["line"]
    )
    assert old["awaiting_md"] == [{"period_month": _period(), "md": 7.25}]

    rest = await _next_order(app_client, app_auth_headers, case, md_total=10)
    rest_line = rest["lines"][0]["id"]
    assert await _consumptions(rest_line) == {_period(): Decimal("7.25")}
    assert await _consumptions(small_line) == {_period(): Decimal("5")}
    old = await _card_line(
        app_client, app_auth_headers, case, case["group"]["id"], case["line"]
    )
    assert old["awaiting_md"] == []


async def test_reimport_does_not_wait_or_settle_twice(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Powtórka miesiąca: te same MD nie czekają podwójnie i nie schodzą drugi raz."""
    case = await _case(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)
    first = await _import(app_client, finance, _split_sheet(case))
    second = await _import(app_client, finance, _split_sheet(case))

    old = await _card_line(
        app_client, app_auth_headers, case, case["group"]["id"], case["line"]
    )
    assert old["awaiting_md"] == [{"period_month": _period(), "md": 12.25}]
    earlier = await app_client.get(
        f"/api/md-consumption/imports/{first['id']}", headers=finance
    )
    assert "superseded" in {row["status"] for row in earlier.json()["rows"]}

    successor = await _next_order(app_client, app_auth_headers, case, md_total=20)
    new_line = successor["lines"][0]["id"]
    assert await _consumptions(new_line) == {_period(): Decimal("12.25")}

    third = await _import(app_client, finance, _split_sheet(case))
    assert {row["status"] for row in third["rows"]} == {"applied"}, third["rows"]
    assert await _consumptions(new_line) == {_period(): Decimal("12.25")}
    assert await _consumptions(case["line"]) == {_period(): Decimal("11.625")}
    assert second["id"] != third["id"]


async def test_single_row_without_number_still_matches_by_name(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Bez wiersza z numerem nic się nie zmienia — dopasowanie po nazwisku."""
    case = await _case(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)

    detail = await _import(app_client, finance, _sheet([(case["name"], 4, "", 0)]))

    [row] = detail["rows"]
    assert row["status"] == "applied", row
    assert row["matched_order_id"] == case["line"]
    assert await _consumptions(case["line"]) == {_period(): Decimal("4")}


async def test_correction_file_without_awaiting_row_retires_the_old_one(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Plik korygujący przeniósł MD na wiersz z numerem — stary wiersz
    oczekujący nie czeka dalej i nie zejdzie z kolejnego zamówienia."""
    case = await _case(app_client, app_auth_headers, monkeypatch, md_total=30)
    finance = await _finance_headers(app_client)
    first = await _import(app_client, finance, _split_sheet(case))
    await _import(
        app_client,
        finance,
        _sheet([(case["name"], 23.875, case["number"], 0)]),
    )

    earlier = await app_client.get(
        f"/api/md-consumption/imports/{first['id']}", headers=finance
    )
    assert "superseded" in {row["status"] for row in earlier.json()["rows"]}
    old = await _card_line(
        app_client, app_auth_headers, case, case["group"]["id"], case["line"]
    )
    assert old["awaiting_md"] == []
    successor = await _next_order(app_client, app_auth_headers, case, md_total=20)
    assert await _consumptions(successor["lines"][0]["id"]) == {}
    assert await _consumptions(case["line"]) == {_period(): Decimal("23.875")}


async def test_correction_file_takes_back_md_already_on_the_next_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """MD zeszły już z kolejnego zamówienia, a plik korygujący dał je na wiersz
    z numerem — wracają z kolejnego zamówienia (lustro nadpisania miesiąca)."""
    case = await _case(app_client, app_auth_headers, monkeypatch, md_total=30)
    finance = await _finance_headers(app_client)
    await _import(app_client, finance, _split_sheet(case))
    successor = await _next_order(app_client, app_auth_headers, case, md_total=20)
    new_line = successor["lines"][0]["id"]
    assert await _consumptions(new_line) == {_period(): Decimal("12.25")}

    await _import(
        app_client,
        finance,
        _sheet([(case["name"], 23.875, case["number"], 0)]),
    )

    assert await _consumptions(new_line) == {_period(): Decimal("0")}
    assert await _consumptions(case["line"]) == {_period(): Decimal("23.875")}
    assert any(
        description.startswith("Cofnięto 12,25 MD")
        for _, description in await _events(successor["id"])
    )


async def test_smaller_awaiting_md_on_reimport_are_corrected_on_the_next_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    case = await _case(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)
    await _import(app_client, finance, _split_sheet(case))
    successor = await _next_order(app_client, app_auth_headers, case, md_total=20)
    new_line = successor["lines"][0]["id"]

    detail = await _import(app_client, finance, _split_sheet(case, awaiting=10))

    assert {row["status"] for row in detail["rows"]} == {"applied"}, detail["rows"]
    assert await _consumptions(new_line) == {_period(): Decimal("10")}

    bigger = await _import(app_client, finance, _split_sheet(case, awaiting=14))
    assert {row["status"] for row in bigger["rows"]} == {"applied"}, bigger["rows"]
    # 10 już leży na kolejnym zamówieniu, 4 schodzą dodatkowo.
    assert await _consumptions(new_line) == {_period(): Decimal("14")}


async def test_activated_draft_order_takes_the_awaiting_md(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Kolejne zamówienie założone jako szkic (np. z PDF-a) — MD schodzą przy
    aktywacji, nie dopiero przy następnym zamówieniu u klienta (audyt 22.10, F69)."""
    case = await _case(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)
    detail = await _import(app_client, finance, _split_sheet(case))

    url = f"/api/clients/{case['client_id']}/order-groups"
    start = _later_start().isoformat()
    created = await app_client.post(
        url,
        headers=app_auth_headers,
        json={
            "order_number": _number(),
            "start_date": start,
            "order_type": "md",
            "md_budget_mode": "per_person",
            "status": "draft",
            "lines": [
                {
                    "contract_id": case["contract_id"],
                    "rate_cost": 1040,
                    "rate_revenue": 1360,
                    "input_mode": "md",
                    "input_value": 20,
                    "start_date": start,
                }
            ],
        },
    )
    assert created.status_code == 201, created.text
    draft = created.json()
    new_line = draft["lines"][0]["id"]
    # Szkic nie jest kolejnym zamówieniem — nic jeszcze nie schodzi.
    assert await _consumptions(new_line) == {}

    activated = await app_client.patch(
        f"{url}/{draft['id']}", headers=app_auth_headers, json={"status": "active"}
    )
    assert activated.status_code == 200, activated.text

    assert await _consumptions(new_line) == {_period(): Decimal("12.25")}
    after = await app_client.get(
        f"/api/md-consumption/imports/{detail['id']}", headers=finance
    )
    assert after.status_code == 200, after.text
    assert {row["status"] for row in after.json()["rows"]} == {"applied"}
    old = await _card_line(
        app_client, app_auth_headers, case, case["group"]["id"], case["line"]
    )
    assert old["awaiting_md"] == []


async def _same_person_at_another_client(contract_id: int) -> tuple[int, int]:
    """Ta sama osoba z umową u drugiego klienta."""
    import uuid

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        first = await db.get(Contract, contract_id)
        client = Client(name=f"MdAwaitingOther-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        contract = Contract(
            candidate_id=first.candidate_id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=_old_start(),
            rate_candidate=Decimal("1040.000"),
            rate_client=Decimal("1360.000"),
        )
        db.add(contract)
        await db.commit()
        return client.id, contract.id


async def test_reimport_at_another_client_keeps_the_settled_awaiting_md(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Klucz powtórki miesiąca to osoba + klient (audyt 22.10, F70): paczka
    z wierszem tej osoby tylko u innego klienta nie cofa MD, które zeszły
    z kolejnego zamówienia pierwszego klienta."""
    case = await _case(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)
    first = await _import(app_client, finance, _split_sheet(case))
    successor = await _next_order(app_client, app_auth_headers, case, md_total=20)
    new_line = successor["lines"][0]["id"]
    assert await _consumptions(new_line) == {_period(): Decimal("12.25")}

    other_client, other_contract = await _same_person_at_another_client(
        case["contract_id"]
    )
    _enable_multi(monkeypatch, case["client_id"], other_client)
    other_number = _number()
    other = await _create_group(
        app_client,
        app_auth_headers,
        other_client,
        other_contract,
        number=other_number,
        start=_old_start(),
        end=None,
        md_total=15,
    )

    second = await _import(
        app_client, finance, _sheet([(case["name"], 5, other_number, 0)])
    )

    [row] = second["rows"]
    assert row["status"] == "applied", row
    assert row["matched_order_id"] == other["lines"][0]["id"]
    assert await _consumptions(new_line) == {_period(): Decimal("12.25")}
    assert not any(
        description.startswith("Cofnięto")
        for _, description in await _events(successor["id"])
    )
    earlier = await app_client.get(
        f"/api/md-consumption/imports/{first['id']}", headers=finance
    )
    assert {r["status"] for r in earlier.json()["rows"]} == {"applied"}


async def test_reimport_at_another_client_keeps_the_row_waiting(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Jak wyżej, ale przed kolejnym zamówieniem: wiersz dalej czeka."""
    case = await _case(app_client, app_auth_headers, monkeypatch)
    finance = await _finance_headers(app_client)
    first = await _import(app_client, finance, _split_sheet(case))

    other_client, other_contract = await _same_person_at_another_client(
        case["contract_id"]
    )
    _enable_multi(monkeypatch, case["client_id"], other_client)
    other_number = _number()
    await _create_group(
        app_client,
        app_auth_headers,
        other_client,
        other_contract,
        number=other_number,
        start=_old_start(),
        end=None,
        md_total=15,
    )
    await _import(app_client, finance, _sheet([(case["name"], 5, other_number, 0)]))

    earlier = await app_client.get(
        f"/api/md-consumption/imports/{first['id']}", headers=finance
    )
    assert "awaiting_order" in {r["status"] for r in earlier.json()["rows"]}
    old = await _card_line(
        app_client, app_auth_headers, case, case["group"]["id"], case["line"]
    )
    assert old["awaiting_md"] == [{"period_month": _period(), "md": 12.25}]
    successor = await _next_order(app_client, app_auth_headers, case, md_total=20)
    assert await _consumptions(successor["lines"][0]["id"]) == {
        _period(): Decimal("12.25")
    }


async def test_reimport_key_takes_the_client_of_the_row_not_just_the_name():
    """Bez bazy: klucz powtórki z wierszy paczki to (osoba, klient)."""
    from types import SimpleNamespace

    from app.api.md_consumption import _reimport_persons

    def line(order_id: int, client_id: int, name: str):
        return SimpleNamespace(
            order=SimpleNamespace(id=order_id, client_id=client_id),
            group=SimpleNamespace(client_id=client_id),
            consultant_name=name,
        )

    def row(name: str, **fields):
        base = {
            "consultant_name": name,
            "awaiting_origin_order_id": None,
            "matched_order_id": None,
            "candidate_order_ids": None,
        }
        return SimpleNamespace(**{**base, **fields})

    candidates = [line(1, 10, "Jan Kowalski"), line(2, 20, "Jan Kowalski")]
    pools = (candidates, [line(3, 30, "Anna Nowak")])

    assert _reimport_persons(
        [row("Jan Kowalski", matched_order_id=2)],
        candidates=candidates,
        line_pools=pools,
    ) == {("Jan Kowalski", 20)}
    assert _reimport_persons(
        [row("Jan Kowalski", awaiting_origin_order_id=1)],
        candidates=candidates,
        line_pools=pools,
    ) == {("Jan Kowalski", 10)}
    assert _reimport_persons(
        [row("Anna Nowak", candidate_order_ids=[3])],
        candidates=candidates,
        line_pools=pools,
    ) == {("Anna Nowak", 30)}
    # Bez dopasowania: linie tej osoby w miesiącu.
    assert _reimport_persons(
        [row("Jan Kowalski")], candidates=candidates, line_pools=pools
    ) == {("Jan Kowalski", 10), ("Jan Kowalski", 20)}
    assert (
        _reimport_persons([row("Ktoś Obcy")], candidates=candidates, line_pools=pools)
        == set()
    )
