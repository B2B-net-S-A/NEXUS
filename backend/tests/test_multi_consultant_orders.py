"""Zamówienia wielo-konsultantowe: bramka klientów, budżet MD, zamiana, import.

Każdy test seeduje własnego klienta i włącza dla niego bramkę przez
podmianę ``multi_consultant_client_ids`` — a nie przez zmienną środowiskową,
bo ``Settings`` czyta env raz przy starcie procesu.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

_TODAY = date.today()


# ── Seed ────────────────────────────────────────────────────────────────────


async def _seed_client_with_contracts(n_contracts: int = 2) -> tuple[int, list[int], list[str]]:
    """Klient + N kontraktów kandydatów. Zwraca (client_id, contract_ids, names)."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"MultiOrderClient-{suffix}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        contract_ids: list[int] = []
        names: list[str] = []
        for i in range(n_contracts):
            cand = Candidate(
                name=f"Jan{i}",
                lastname=f"Kowalski-{suffix}-{i}",
                email=f"mo-{suffix}-{i}@example.com",
            )
            db.add(cand)
            await db.commit()
            await db.refresh(cand)
            contract = Contract(
                candidate_id=cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=_TODAY - timedelta(days=30),
                rate_candidate=Decimal("100.000"),
                rate_client=Decimal("150.000"),
            )
            db.add(contract)
            await db.commit()
            await db.refresh(contract)
            contract_ids.append(contract.id)
            names.append(f"{cand.name} {cand.lastname}")
        return client.id, contract_ids, names


def _enable_for(monkeypatch, *client_ids: int) -> None:
    from app.services import multi_consultant_orders as mco

    monkeypatch.setattr(
        mco, "multi_consultant_client_ids", lambda: frozenset(client_ids)
    )


def _line_payload(contract_id: int, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "rate_cost": 1000,
        "rate_revenue": 1200,
        "input_mode": "md",
        "input_value": 50,
        "start_date": (_TODAY - timedelta(days=10)).isoformat(),
    }
    payload.update(overrides)
    return payload


async def _create_group(
    app_client: AsyncClient, headers: dict, client_id: int, lines: list[dict]
) -> dict:
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"445-{uuid.uuid4().hex[:4]}",
            "start_date": (_TODAY - timedelta(days=10)).isoformat(),
            "lines": lines,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Bramka klientów ─────────────────────────────────────────────────────────


async def test_gate_rejects_client_outside_allowlist(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Klient spoza listy nie może założyć zamówienia wielo-konsultantowego."""
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch)  # pusta lista — nikt nie jest objęty

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": "445",
            "start_date": _TODAY.isoformat(),
            "lines": [_line_payload(contracts[0])],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert "MULTI_CONSULTANT_ORDER_CLIENT_IDS" in resp.text


async def test_gate_returns_empty_list_not_forbidden(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Odczyt u klienta spoza listy zwraca pustkę, nie 403.

    403 renderuje się jak awaria; tutaj naprawdę nie ma czego pokazać.
    """
    client_id, _, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch)

    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"groups": [], "total_groups": 0, "total_consultants": 0}


# ── Budżet MD ───────────────────────────────────────────────────────────────


async def test_budget_from_amount_divides_by_revenue_rate(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Tryb „kwota": 60 000 zł / 1200 zł/MD = 50 MD."""
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)

    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_line_payload(contracts[0], input_mode="amount", input_value=60000)],
    )
    line = group["lines"][0]
    assert line["md_total"] == pytest.approx(50.0)
    assert line["md_remaining"] == pytest.approx(50.0)


async def test_two_consultants_share_one_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Jedno zamówienie, dwie linie, każda z własnym budżetem."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)

    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [
            _line_payload(contracts[0], input_value=50),
            _line_payload(contracts[1], rate_cost=800, rate_revenue=950, input_value=63),
        ],
    )
    assert len(group["lines"]) == 2
    assert group["active_consultants"] == 2
    assert {line["md_total"] for line in group["lines"]} == {50.0, 63.0}


async def test_line_rejects_zero_revenue_rate(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Stawka przychodowa jest dzielnikiem — zero odpada na wejściu."""
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": "446",
            "start_date": _TODAY.isoformat(),
            "lines": [_line_payload(contracts[0], rate_revenue=0)],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


# ── Zamiana kontraktora ─────────────────────────────────────────────────────


async def test_swap_preserves_order_value_in_pln(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """md_nowe × stawka_nowa == md_pozostałe × stawka_stara."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)

    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    old_line = group["lines"][0]

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{old_line['id']}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    new_line = resp.json()

    # 50 MD × 1200 zł = 60 000 zł → 60 000 / 950 = 63.157894 MD
    assert new_line["md_total"] == pytest.approx(60000 / 950, rel=1e-6)
    assert new_line["predecessor_order_id"] == old_line["id"]
    assert new_line["md_total"] * 950 == pytest.approx(50 * 1200, rel=1e-6)


async def test_swap_closes_old_line_and_keeps_history(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Stara linia dostaje datę zakończenia; historia niesie OBIE stawki."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)

    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    old_id = group["lines"][0]["id"]

    await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{old_id}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    lines = {line["id"]: line for line in listing.json()["groups"][0]["lines"]}
    assert lines[old_id]["is_active"] is False
    assert lines[old_id]["end_date"] == _TODAY.isoformat()

    events = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group['id']}/events",
        headers=app_auth_headers,
    )
    swap_events = [
        e for e in events.json()["events"] if e["event_type"] == "zamiana_kontraktora"
    ]
    assert len(swap_events) == 1
    payload = swap_events[0]["payload"]
    # Bez kompletu tych danych nie da się rozliczyć faktury za miesiąc zamiany.
    for key in (
        "old_rate_revenue",
        "new_rate_revenue",
        "old_md_remaining",
        "new_md_total",
        "swap_date",
    ):
        assert key in payload, key


async def test_future_swap_keeps_old_line_active(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zamiana zaplanowana na przyszłość nie wyłącza pracującego konsultanta."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)

    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    old_id = group["lines"][0]["id"]
    future = _TODAY + timedelta(days=20)

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{old_id}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": future.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    lines = {line["id"]: line for line in listing.json()["groups"][0]["lines"]}
    assert lines[old_id]["is_active"] is True, "przyszła zamiana wyłączyła konsultanta"
    assert lines[old_id]["end_date"] == future.isoformat()


async def test_swap_gives_successor_the_planned_end_date(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Następca dziedziczy planowany koniec, a nie datę zamiany.

    Odczyt `end_date` PO nadpisaniu go datą zamiany dawał następcy jeden dzień
    pracy — linia kończyłaby się w dniu, w którym się zaczyna.
    """
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)
    planned_end = _TODAY + timedelta(days=120)

    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_line_payload(contracts[0], end_date=planned_end.isoformat())],
    )
    old_id = group["lines"][0]["id"]

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{old_id}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    new_line = resp.json()
    assert new_line["start_date"] == _TODAY.isoformat()
    assert new_line["end_date"] == planned_end.isoformat(), (
        "następca dostał datę zamiany zamiast planowanego końca zaangażowania"
    )


# ── Import MD ───────────────────────────────────────────────────────────────


def _xlsx(rows: list[tuple[str, object]]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Konsultant", "MD"])
    for name, md in rows:
        ws.append([name, md])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _upload(
    app_client: AsyncClient, headers: dict, rows: list[tuple[str, object]], month: str
):
    return await app_client.post(
        "/api/md-consumption/imports",
        files={
            "file": (
                "raport.xlsx",
                _xlsx(rows),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"period_month": month},
        headers=headers,
    )


async def test_import_subtracts_md_and_is_idempotent(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Powtórka tego samego miesiąca NADPISUJE, nie odejmuje drugi raz."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    month = _TODAY.strftime("%Y-%m")

    first = await _upload(app_client, app_auth_headers, [(names[0], 15)], month)
    assert first.status_code == 201, first.text
    assert first.json()["rows_applied"] == 1

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    assert listing.json()["groups"][0]["lines"][0]["md_remaining"] == pytest.approx(35.0)

    second = await _upload(app_client, app_auth_headers, [(names[0], 15)], month)
    assert second.status_code == 201, second.text

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    remaining = listing.json()["groups"][0]["lines"][0]["md_remaining"]
    assert remaining == pytest.approx(35.0), (
        f"powtórny import odjął MD drugi raz (pozostało {remaining}, oczekiwano 35)"
    )
    assert group["id"]


async def test_import_marks_ambiguous_without_applying(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Dwie aktywne linie tej samej osoby → „wymaga przypisania", zero zmian."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.contract import Contract, ContractStatus
    from sqlalchemy import select

    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)

    # Drugi kontrakt tego SAMEGO kandydata — jedno nazwisko, dwie linie.
    async with AsyncSessionLocal() as db:
        first = await db.scalar(select(Contract).where(Contract.id == contracts[0]))
        cand = await db.scalar(
            select(Candidate).where(Candidate.id == first.candidate_id)
        )
        twin = Contract(
            candidate_id=cand.id,
            client_id=client_id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=30),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(twin)
        await db.commit()
        await db.refresh(twin)
        twin_id = twin.id

    await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(twin_id)]
    )

    resp = await _upload(
        app_client, app_auth_headers, [(names[0], 10)], _TODAY.strftime("%Y-%m")
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rows_ambiguous"] == 1
    assert body["rows_applied"] == 0

    row = body["rows"][0]
    assert row["status"] == "needs_assignment"
    assert len(row["options"]) == 2

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    for grp in listing.json()["groups"]:
        for line in grp["lines"]:
            assert line["md_remaining"] == pytest.approx(50.0), (
                "niejednoznaczny wiersz zmienił budżet bez decyzji człowieka"
            )

    # Ręczne rozstrzygnięcie stosuje MD do WSKAZANEJ linii.
    chosen = row["options"][0]["order_id"]
    assign = await app_client.post(
        f"/api/md-consumption/imports/{body['id']}/rows/{row['id']}/assign",
        json={"order_id": chosen},
        headers=app_auth_headers,
    )
    assert assign.status_code == 200, assign.text
    assert assign.json()["status"] == "applied"


async def test_import_unmatched_row_does_not_break_the_rest(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Nazwisko bez aktywnej linii nie przerywa importu pozostałych wierszy."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )

    resp = await _upload(
        app_client,
        app_auth_headers,
        [("Nikt Taki", 5), (names[0], 12)],
        _TODAY.strftime("%Y-%m"),
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rows_unmatched"] == 1
    assert body["rows_applied"] == 1


async def test_assign_rejects_a_line_closed_since_the_import(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Linia domknięta między importem a rozstrzygnięciem nie przyjmuje MD.

    Zużycie zapisane na nieaktywnej linii nie pojawiłoby się już w żadnym
    dopasowaniu — nie da się go zobaczyć ani cofnąć z interfejsu, a policzy
    się do faktury.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.contract import Contract, ContractStatus
    from sqlalchemy import select

    client_id, contracts, names = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)

    # Dwie aktywne linie tej samej osoby → wiersz „wymaga przypisania".
    async with AsyncSessionLocal() as db:
        first = await db.scalar(select(Contract).where(Contract.id == contracts[0]))
        cand = await db.scalar(
            select(Candidate).where(Candidate.id == first.candidate_id)
        )
        twin = Contract(
            candidate_id=cand.id,
            client_id=client_id,
            status=ContractStatus.active,
            start_date=_TODAY - timedelta(days=30),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(twin)
        await db.commit()
        await db.refresh(twin)
        twin_id = twin.id

    await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    group_b = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(twin_id)]
    )

    body = (
        await _upload(
            app_client, app_auth_headers, [(names[0], 10)], _TODAY.strftime("%Y-%m")
        )
    ).json()
    row = body["rows"][0]
    assert row["status"] == "needs_assignment"

    # Domknięcie jednej z linii PO imporcie — zamiana kontraktora.
    target = group_b["lines"][0]["id"]
    swap = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group_b['id']}/lines/{target}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert swap.status_code == 201, swap.text

    assign = await app_client.post(
        f"/api/md-consumption/imports/{body['id']}/rows/{row['id']}/assign",
        json={"order_id": target},
        headers=app_auth_headers,
    )
    assert assign.status_code == 409, assign.text
    assert "nie jest już aktywna" in assign.text


async def test_md_remaining_may_go_negative(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Przekroczony budżet jest zapisywany, nie ścinany do zera."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )

    resp = await _upload(
        app_client, app_auth_headers, [(names[0], 70)], _TODAY.strftime("%Y-%m")
    )
    assert resp.status_code == 201, resp.text

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    assert listing.json()["groups"][0]["lines"][0]["md_remaining"] == pytest.approx(
        -20.0
    )


async def test_manual_adjustment_survives_reimport(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Korekta ręczna nie znika przy najbliższym imporcie miesiąca."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    line_id = group["lines"][0]["id"]
    month = _TODAY.strftime("%Y-%m")

    await _upload(app_client, app_auth_headers, [(names[0], 10)], month)  # → 40

    patch = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{line_id}",
        json={"md_remaining": 45},
        headers=app_auth_headers,
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["md_remaining"] == pytest.approx(45.0)

    await _upload(app_client, app_auth_headers, [(names[0], 10)], month)

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    remaining = listing.json()["groups"][0]["lines"][0]["md_remaining"]
    assert remaining == pytest.approx(45.0), (
        f"import skasował korektę ręczną (pozostało {remaining}, oczekiwano 45)"
    )


# ── Brak regresji dla klientów jednoosobowych ───────────────────────────────


async def test_legacy_single_consultant_orders_untouched(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zamówienie spoza grupy zachowuje kontrakt i puste pola MD.

    To jest asercja braku regresji: cały system czyta zamówienie przez jego
    kontrakt, więc gdyby model wielo-konsultantowy zdjął `contract_id`, ten
    test padłby razem ze skanerem wygasania i syncem terminacji.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from sqlalchemy import select

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch)  # klient NIE jest objęty nowym modelem

    async with AsyncSessionLocal() as db:
        order = ClientOrder(
            client_id=client_id,
            contract_id=contracts[0],
            title="Legacy",
            status=ClientOrderStatus.active,
            start_date=_TODAY,
        )
        db.add(order)
        await db.commit()
        await db.refresh(order)

        stored = await db.scalar(select(ClientOrder).where(ClientOrder.id == order.id))
        assert stored.contract_id == contracts[0]
        assert stored.order_group_id is None
        assert stored.md_total is None
        assert stored.md_remaining is None
        assert Decimal(str(stored.md_manual_adjustment)) == Decimal("0")

    grouped = await app_client.get(
        f"/api/clients/{client_id}/orders", headers=app_auth_headers
    )
    assert grouped.status_code == 200, grouped.text
    assert grouped.json()["total_contractors"] >= 1
