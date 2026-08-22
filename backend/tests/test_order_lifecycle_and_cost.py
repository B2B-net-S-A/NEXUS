"""Cykl życia zamówienia, zamówienia kosztowe i powiadomienia Delivery Leada.

Trzy obszary z jednej migracji (0231), więc jeden plik — łączy je ten sam
wiersz ``client_order_groups``.

Każdy test seeduje własnego klienta i włącza dla niego bramki przez podmianę
``multi_consultant_client_ids`` / ``cost_order_client_ids``, a nie przez
zmienną środowiskową: ``Settings`` czyta env raz przy starcie procesu.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today

# `business_today()`, nie `date.today()`: cykl życia grupy zamówień jest
# datowany DNIEM BIZNESOWYM (Europe/Warsaw) — tak liczy
# `order_group_lifecycle.materialize_scheduled_order_groups`, wołany
# idempotentnie przy KAŻDYM odczycie listy. Kontener chodzi w UTC, więc między
# 22:00 UTC a północą (latem) „jutro" wg `date.today()` jest już DZISIAJ wg
# firmy: zamówienie założone jako `scheduled` materializuje się na `active`
# jeszcze zanim test zdąży sprawdzić zagnieżdżenie, i widzi dwie równorzędne
# karty zamiast jednej. Czerwień zależałaby od GODZINY biegu CI, nie od kodu.
# Ten sam wzorzec ma już `test_order_activation_gates_and_group_materializer`.
_TODAY = business_today()


# ── Seed ────────────────────────────────────────────────────────────────────


async def _seed_client_with_contracts(
    n_contracts: int = 2,
) -> tuple[int, list[int], list[str]]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"LifecycleClient-{suffix}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        contract_ids: list[int] = []
        names: list[str] = []
        for i in range(n_contracts):
            cand = Candidate(
                name=f"Kon{i}",
                lastname=f"Sultant-{suffix}-{i}",
                email=f"lc-{suffix}-{i}@example.com",
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


def _enable_multi(monkeypatch, *client_ids: int) -> None:
    from app.services import multi_consultant_orders as mco

    monkeypatch.setattr(
        mco, "multi_consultant_client_ids", lambda: frozenset(client_ids)
    )


def _enable_cost(monkeypatch, *client_ids: int) -> None:
    from app.services import cost_orders as co

    monkeypatch.setattr(co, "cost_order_client_ids", lambda: frozenset(client_ids))


def _md_line(contract_id: int, **overrides) -> dict:
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


def _cost_line(contract_id: int, **overrides) -> dict:
    """Linia zamówienia kosztowego — BEZ budżetu MD (pula jest wspólna)."""
    payload = {
        "contract_id": contract_id,
        "rate_cost": 1000,
        "rate_revenue": 1200,
        "start_date": (_TODAY - timedelta(days=10)).isoformat(),
    }
    payload.update(overrides)
    return payload


async def _create_group(
    app_client: AsyncClient,
    headers: dict,
    client_id: int,
    lines: list[dict],
    **extra,
) -> dict:
    body = {
        "order_number": f"445-{uuid.uuid4().hex[:4]}",
        "start_date": (_TODAY - timedelta(days=10)).isoformat(),
        "lines": lines,
    }
    body.update(extra)
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups", json=body, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _seed_user(role_value: str, client_id: int | None = None):
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    email = f"lc-{role_value}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"LC {role_value}",
            role=UserRole(role_value),
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        if client_id is not None and role_value == "delivery_lead":
            db.add(
                DeliveryLeadClientAssignment(
                    client_id=client_id, delivery_lead_user_id=user.id
                )
            )
            await db.commit()
        return user.id, email, password


async def _headers_for(app_client: AsyncClient, email: str, password: str) -> dict:
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ── Usuwanie ────────────────────────────────────────────────────────────────


async def test_delete_line_removes_only_that_consultant(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Usunięcie konsultanta nie rusza reszty zamówienia (ticket §1)."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0]), _md_line(contracts[1])],
    )
    victim = group["lines"][0]["id"]

    resp = await app_client.delete(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{victim}",
        headers=app_auth_headers,
    )
    assert resp.status_code == 204, resp.text

    after = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    lines = after.json()["groups"][0]["lines"]
    assert [line["id"] for line in lines] == [group["lines"][1]["id"]]


async def test_delete_line_leaves_no_trace_in_history(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """„Znika bez śladu" — wpis o dodaniu tej osoby też znika (ticket §1)."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0]), _md_line(contracts[1])],
    )
    victim = group["lines"][0]["id"]

    await app_client.delete(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{victim}",
        headers=app_auth_headers,
    )
    events = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group['id']}/events",
        headers=app_auth_headers,
    )
    assert all(event["order_id"] != victim for event in events.json()["events"]), (
        "wpis o usuniętej osobie został w historii"
    )


async def test_delete_group_removes_its_lines(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Do 0231 zamówienie z liniami było nieusuwalne (409) — teraz znika całe."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_md_line(contracts[0]), _md_line(contracts[1])],
    )

    resp = await app_client.delete(
        f"/api/clients/{client_id}/order-groups/{group['id']}",
        headers=app_auth_headers,
    )
    assert resp.status_code == 204, resp.text

    after = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    assert after.json()["groups"] == []


async def test_delete_line_with_history_detaches_instead_of_erasing(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Linia z rozliczeniem NIE jest kasowana — zamówienie niesie fakty.

    Kasowanie zabrałoby wpisy konsumpcji, które powstały poza tym ekranem.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.md_consumption import (
        CONSUMPTION_SOURCE_IMPORT,
        ClientOrderMdConsumption,
    )

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    line_id = group["lines"][0]["id"]

    async with AsyncSessionLocal() as db:
        db.add(
            ClientOrderMdConsumption(
                order_id=line_id,
                period_month="2026-07",
                md_reported=Decimal("10"),
                source=CONSUMPTION_SOURCE_IMPORT,
            )
        )
        await db.commit()

    resp = await app_client.delete(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{line_id}",
        headers=app_auth_headers,
    )
    assert resp.status_code == 204, resp.text

    async with AsyncSessionLocal() as db:
        survived = await db.get(ClientOrder, line_id)
        assert survived is not None, "linia z historią została skasowana"
        assert survived.order_group_id is None, "linia nadal wisi na zamówieniu"


# ── Zakończenie i przywrócenie ──────────────────────────────────────────────


async def test_close_moves_group_and_closes_lines(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )

    closure = (_TODAY - timedelta(days=1)).isoformat()
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/close",
        json={"closure_date": closure, "closure_reason": "Koniec projektu"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "completed"
    assert body["closure_date"] == closure
    assert body["lines"][0]["is_active"] is False


async def test_close_in_the_future_does_not_switch_off_a_working_consultant(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Data zapisuje się zawsze, status `completed` tylko gdy dzień nadszedł.

    Lustro syncu terminacji kontraktu — bez tego zakończenie zaplanowane na
    przyszłość wyłączałoby kogoś, kto dziś jeszcze pracuje.
    """
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )

    future = (_TODAY + timedelta(days=30)).isoformat()
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/close",
        json={"closure_date": future},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    line = resp.json()["lines"][0]
    assert line["is_active"] is True, "konsultant wyłączony przed czasem"
    assert line["end_date"] == future


async def test_reopen_restores_active_and_clears_closure(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/close",
        json={"closure_date": _TODAY.isoformat()},
        headers=app_auth_headers,
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/reopen",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["closure_date"] is None


async def test_reopen_refuses_exhausted_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wyczerpany budżet to nie pomyłka w dacie — przywrócenie nic nie da."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import GROUP_STATUS_EXHAUSTED, ClientOrderGroup

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        is_cost_based=True,
        budget_amount=1000,
    )
    async with AsyncSessionLocal() as db:
        row = await db.get(ClientOrderGroup, group["id"])
        row.status = GROUP_STATUS_EXHAUSTED
        row.budget_remaining = Decimal("0")
        await db.commit()

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/reopen",
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "wyczerpane" in resp.text.lower()


# ── Przedłużenie ────────────────────────────────────────────────────────────


async def test_extend_creates_successor_linked_to_predecessor(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/extend",
        json={
            "order_number": "446",
            "start_date": (_TODAY + timedelta(days=1)).isoformat(),
            "lines": [
                _md_line(
                    contracts[0], start_date=(_TODAY + timedelta(days=1)).isoformat()
                )
            ],
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["predecessor_group_id"] == group["id"]
    assert body["order_number"] == "446"
    assert len(body["lines"]) == 1
    # Poprzednik ZOSTAJE — na jego podstawie rozliczono już faktury. Przyszły
    # następca jest jednak zagnieżdżony pod bieżącą kartą, a nie renderowany
    # jako drugie równorzędne zamówienie.
    listed = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    assert listed.status_code == 200, listed.text
    listed_body = listed.json()
    assert len(listed_body["groups"]) == 1
    assert [future["id"] for future in listed_body["groups"][0]["future_orders"]] == [
        body["id"]
    ]


async def test_extend_inherits_settlement_type(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Przedłużenie kosztowego jest kosztowe i wymaga kwoty."""
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        is_cost_based=True,
        budget_amount=50000,
    )

    without_budget = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/extend",
        json={"order_number": "447", "start_date": _TODAY.isoformat(), "lines": []},
        headers=app_auth_headers,
    )
    assert without_budget.status_code == 422, without_budget.text

    ok = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/extend",
        json={
            "order_number": "447",
            "start_date": _TODAY.isoformat(),
            "budget_amount": 30000,
            "lines": [],
        },
        headers=app_auth_headers,
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["is_cost_based"] is True
    assert ok.json()["budget_remaining"] == pytest.approx(30000.0)


# ── Uprawnienia ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("role", ["tac", "recruiter", "sourcer"])
async def test_lifecycle_actions_forbidden_for_excluded_roles(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, role: str
):
    """Ticket wymienia te trzy role przez wykluczenie."""
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    _, email, password = await _seed_user(role, client_id)
    headers = await _headers_for(app_client, email, password)

    for method, path in (
        ("delete", f"/api/clients/{client_id}/order-groups/{group['id']}"),
        (
            "delete",
            f"/api/clients/{client_id}/order-groups/{group['id']}"
            f"/lines/{group['lines'][0]['id']}",
        ),
        ("post", f"/api/clients/{client_id}/order-groups/{group['id']}/reopen"),
    ):
        resp = await getattr(app_client, method)(path, headers=headers)
        assert resp.status_code == 403, f"{role} {method} {path} -> {resp.status_code}"


@pytest.mark.parametrize("role", ["head_of_recruitment", "finance"])
async def test_lifecycle_actions_allowed_for_hor_and_finance(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch, role: str
):
    """Świadome poszerzenie: ticket przyznaje te akcje wszystkim poza trójką.

    Konsekwencja jest jawna — Head of Recruitment dostaje je u WSZYSTKICH
    klientów (przechodzi guardy globalnie), a Finanse widzą tu nazwisko
    konsultanta. Obie decyzje potwierdzone przy planowaniu.
    """
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    _, email, password = await _seed_user(role)
    headers = await _headers_for(app_client, email, password)

    # Odczyt musi działać, inaczej to uprawnienie do niewidocznego przycisku.
    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert listing.status_code == 200, listing.text

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/close",
        json={"closure_date": _TODAY.isoformat()},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    # WSZYSTKIE cztery akcje, nie tylko zakończenie. Pierwsza wersja tego testu
    # sprawdzała samo `close` i przepuściła błąd: `delete_order_group` wisiał na
    # `DlAssignedOrAdmin`, który odrzuca rolę Finanse na poziomie zależności —
    # więc ta rola mogła zamknąć zamówienie, ale nie usunąć.
    reopened = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/reopen",
        headers=headers,
    )
    assert reopened.status_code == 200, reopened.text

    extended = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/extend",
        json={
            "order_number": f"ext-{uuid.uuid4().hex[:4]}",
            "start_date": _TODAY.isoformat(),
            "lines": [],
        },
        headers=headers,
    )
    assert extended.status_code == 201, extended.text

    deleted_line = await app_client.delete(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{group['lines'][0]['id']}",
        headers=headers,
    )
    assert deleted_line.status_code == 204, deleted_line.text

    deleted_group = await app_client.delete(
        f"/api/clients/{client_id}/order-groups/{group['id']}",
        headers=headers,
    )
    assert deleted_group.status_code == 204, deleted_group.text


async def test_rate_gate_did_not_leak_to_lifecycle_roles(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Poszerzenie cyklu życia NIE otworzyło stawek linii.

    `_has_md_line_management_role` zostaje przy admin + Delivery Lead; ten test
    broni tej granicy przed „uproszczeniem" do jednej listy ról.
    """
    from app.api.client_order_groups import _has_md_line_management_role
    from app.models.user import User, UserRole

    for role in (UserRole.head_of_recruitment, UserRole.finance):
        assert not _has_md_line_management_role(User(role=role, roles=[role.value]))
    for role in (UserRole.admin, UserRole.delivery_lead):
        assert _has_md_line_management_role(User(role=role, roles=[role.value]))


# ── Zamówienie kosztowe: rozliczenie fakturami ──────────────────────────────


def _sheet(rows: list[tuple[str, float, str, float]]) -> bytes:
    """Arkusz MD z kolumnami „Uwagi" i „Faktura" (jak u Polkomtela)."""
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Imię i nazwisko", "Ilość MD", "Uwagi", "Faktura"])
    for name, md, notes, invoice in rows:
        ws.append([name, md, notes, invoice])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _finance_headers(app_client: AsyncClient) -> dict:
    _, email, password = await _seed_user("finance")
    return await _headers_for(app_client, email, password)


#: Miesiąc importu MUSI zachodzić na okres linii — `active_cost_lines`
#: dopasowuje wyłącznie linie obowiązujące w danym miesiącu, więc sztywna data
#: z przeszłości dawałaby zero trafień i test „przechodziłby" z zerem zmian.
_PERIOD = _TODAY.strftime("%Y-%m")


async def _import_sheet(
    app_client: AsyncClient, headers: dict, payload: bytes, period: str = _PERIOD
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


async def test_invoice_import_reduces_the_shared_budget(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Przykład z ticketu: 50 000 − 20 000 − 5 000 − 5 000 = 20 000."""
    client_id, contracts, names = await _seed_client_with_contracts(3)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(c) for c in contracts],
        order_number="4500719650",
        is_cost_based=True,
        budget_amount=50000,
    )
    finance = await _finance_headers(app_client)

    await _import_sheet(
        app_client,
        finance,
        _sheet(
            [
                (names[0], 10, "SAP 4500719650", 20000),
                (names[1], 5, "SAP 4500719650", 5000),
                (names[2], 5, "SAP 4500719650", 5000),
            ]
        ),
    )

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    body = next(g for g in listing.json()["groups"] if g["id"] == group["id"])
    assert body["budget_remaining"] == pytest.approx(20000.0)
    assert body["budget_used"] == pytest.approx(30000.0)
    assert body["lines"][0]["invoiced_total"] == pytest.approx(20000.0)


async def test_reimporting_the_same_month_does_not_subtract_twice(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Klucz idempotencji `(linia, miesiąc)` — nie ostrożność w kodzie."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        order_number="4500719651",
        is_cost_based=True,
        budget_amount=50000,
    )
    finance = await _finance_headers(app_client)
    payload = _sheet([(names[0], 10, "SAP 4500719651", 20000)])

    await _import_sheet(app_client, finance, payload)
    await _import_sheet(app_client, finance, payload)

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    body = next(g for g in listing.json()["groups"] if g["id"] == group["id"])
    assert body["budget_remaining"] == pytest.approx(30000.0)


async def test_two_rows_for_one_person_are_summed_not_overwritten(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Dwa wiersze tej samej osoby na tym samym numerze SUMUJĄ się.

    Bez sumowania przed zapisem drugi wiersz nadpisałby pierwszy (UNIQUE na
    (linia, miesiąc)) i kwota po cichu zniknęłaby z rozliczenia.
    """
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        order_number="4500719652",
        is_cost_based=True,
        budget_amount=50000,
    )
    finance = await _finance_headers(app_client)

    await _import_sheet(
        app_client,
        finance,
        _sheet(
            [
                (names[0], 5, "SAP 4500719652", 10000),
                (names[0], 5, "SAP 4500719652", 5000),
            ]
        ),
    )

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    body = next(g for g in listing.json()["groups"] if g["id"] == group["id"])
    assert body["budget_remaining"] == pytest.approx(35000.0)
    assert body["lines"][0]["invoiced_total"] == pytest.approx(15000.0)


async def test_budget_floors_at_zero_and_names_who_was_short(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Reszta nie schodzi poniżej zera, a brakująca kwota ma właściciela."""
    client_id, contracts, names = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0]), _cost_line(contracts[1])],
        order_number="4500719653",
        is_cost_based=True,
        budget_amount=10000,
    )
    finance = await _finance_headers(app_client)

    await _import_sheet(
        app_client,
        finance,
        _sheet(
            [
                (names[0], 5, "SAP 4500719653", 8000),
                (names[1], 5, "SAP 4500719653", 5000),
            ]
        ),
    )

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    body = next(g for g in listing.json()["groups"] if g["id"] == group["id"])
    assert body["budget_remaining"] == pytest.approx(0.0)
    short = [line for line in body["lines"] if (line["unsettled_total"] or 0) > 0]
    assert len(short) == 1, "brakująca kwota nie została przypisana do osoby"
    assert short[0]["unsettled_total"] == pytest.approx(3000.0)


async def test_exhausted_budget_blocks_adding_a_consultant(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, names = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        order_number="4500719654",
        is_cost_based=True,
        budget_amount=10000,
    )
    finance = await _finance_headers(app_client)
    await _import_sheet(
        app_client, finance, _sheet([(names[0], 5, "SAP 4500719654", 10000)])
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
        json=_cost_line(contracts[1]),
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert "wyczerpane" in resp.text.lower()


async def test_unmatched_order_number_is_recorded_not_guessed(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """System nie zgaduje — wiersz zostaje z powodem niedopasowania."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        order_number="4500719655",
        is_cost_based=True,
        budget_amount=50000,
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client,
        finance,
        _sheet([(names[0], 5, "SAP 9999999999", 5000)]),
    )
    row = detail["rows"][0]
    assert row["cost_status"] == "unmatched_number"
    assert detail["rows_cost_unmatched"] == 1


async def test_row_without_invoice_amount_is_not_flagged(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Bez kwoty nie ma czego odjąć — czerwień byłaby fałszywym alarmem."""
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        order_number="4500719656",
        is_cost_based=True,
        budget_amount=50000,
    )
    finance = await _finance_headers(app_client)

    detail = await _import_sheet(
        app_client, finance, _sheet([(names[0], 5, "notatka bez numeru", 0)])
    )
    assert detail["rows"][0]["cost_status"] is None
    assert detail["rows_cost_unmatched"] == 0


async def test_impossible_closure_date_is_refused_not_a_500(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Data przed startem zamówienia narusza CHECK dat — ma być 422, nie 500."""
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/close",
        json={"closure_date": (_TODAY - timedelta(days=365)).isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_clearing_the_budget_of_a_cost_order_is_refused(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Jawny `null` przechodzi walidację schematu, ale narusza CHECK w bazie."""
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        is_cost_based=True,
        budget_amount=50000,
    )

    resp = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}",
        json={"budget_amount": None},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text


async def test_raising_the_budget_reopens_an_exhausted_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Korekta kwoty MUSI przeliczyć rozliczenie od zera.

    Bez przeliczenia zamówienie zostawałoby w „Wyczerpanych" z dodatnią resztą
    — stan, którego interfejs nie umie wytłumaczyć.
    """
    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        order_number="4500719657",
        is_cost_based=True,
        budget_amount=10000,
    )
    finance = await _finance_headers(app_client)
    await _import_sheet(
        app_client, finance, _sheet([(names[0], 5, "SAP 4500719657", 10000)])
    )

    exhausted = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=app_auth_headers
    )
    assert (
        next(g for g in exhausted.json()["groups"] if g["id"] == group["id"])["status"]
        == "exhausted"
    )

    resp = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}",
        json={"budget_amount": 30000},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "active"
    assert body["budget_remaining"] == pytest.approx(20000.0)


async def test_re_exhaustion_after_a_budget_raise_alerts_again(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Drugie wyczerpanie po korekcie kwoty MUSI dać nowy alert.

    Klucz oparty wyłącznie na `group.id` wpadałby w `ON CONFLICT DO NOTHING`
    i nikt by się o tym nie dowiedział — a to jest moment, w którym kończą się
    pieniądze na projekcie.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.dl_alert import ALERT_COST_ORDER_EXHAUSTED, DlAlert
    from sqlalchemy import select

    client_id, contracts, names = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    _, dl_email, dl_pass = await _seed_user("delivery_lead", client_id)
    await _headers_for(app_client, dl_email, dl_pass)

    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        order_number="4500719658",
        is_cost_based=True,
        budget_amount=10000,
    )
    finance = await _finance_headers(app_client)
    await _import_sheet(
        app_client, finance, _sheet([(names[0], 5, "SAP 4500719658", 10000)])
    )

    # Korekta kwoty w górę → zamówienie wraca na `active`…
    raised = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}",
        json={"budget_amount": 15000},
        headers=app_auth_headers,
    )
    assert raised.status_code == 200, raised.text
    assert raised.json()["status"] == "active"

    # …i zostaje wyczerpane po raz drugi.
    exhausted_again = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}",
        json={"budget_amount": 10000},
        headers=app_auth_headers,
    )
    assert exhausted_again.status_code == 200, exhausted_again.text
    assert exhausted_again.json()["status"] == "exhausted"

    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(DlAlert).where(
                    DlAlert.client_id == client_id,
                    DlAlert.alert_type == ALERT_COST_ORDER_EXHAUSTED,
                )
            )
        ).all()
        assert len(rows) >= 2, (
            "drugie wyczerpanie nie wygenerowało alertu — klucz dedupu nie "
            "rozróżnia epizodów budżetu"
        )


async def test_client_api_exposes_both_order_mode_flags(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """`GET /api/clients/{id}` MUSI zwracać obie flagi trybu zamówień.

    Ten test istnieje, bo `cost_orders_enabled` zostało zaplanowane, front je
    konsumował — i nigdy nie powstało. Checkbox „Zamówienie kosztowe" nie
    renderowałby się NIGDY, nawet po ustawieniu `COST_ORDER_CLIENT_IDS`,
    a żaden inny test tego nie widział: backendowe patchują serwis wprost,
    frontendowe dostają flagę propsem. Dziura była dokładnie w szczelinie
    między nimi — czyli w odpowiedzi API, której nikt nie asertował.
    """
    client_id, _, _ = await _seed_client_with_contracts(1)

    _enable_multi(monkeypatch)
    _enable_cost(monkeypatch)
    off = await app_client.get(f"/api/clients/{client_id}", headers=app_auth_headers)
    assert off.status_code == 200, off.text
    body = off.json()
    assert body["multi_consultant_orders_enabled"] is False
    assert body["cost_orders_enabled"] is False, "brak pola = martwy checkbox"

    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    on = await app_client.get(f"/api/clients/{client_id}", headers=app_auth_headers)
    assert on.status_code == 200, on.text
    assert on.json()["multi_consultant_orders_enabled"] is True
    assert on.json()["cost_orders_enabled"] is True


async def test_cost_flag_is_independent_of_the_md_flag(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """BIK i BNP rozliczają się wyłącznie na MD — u nich checkbox ma NIE być."""
    client_id, _, _ = await _seed_client_with_contracts(1)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch)  # pusta lista kosztowych

    resp = await app_client.get(f"/api/clients/{client_id}", headers=app_auth_headers)
    body = resp.json()
    assert body["multi_consultant_orders_enabled"] is True
    assert body["cost_orders_enabled"] is False


# ── Zamiana kontraktora na zamówieniu kosztowym ─────────────────────────────
#
# Guard zamiany był pisany wyłącznie pod tryb MD (`md_total is None` → 422),
# a linia zamówienia KOSZTOWEGO ma `md_total = None` z definicji: pula mieszka
# na grupie. Przycisk „Zamień kontraktora" renderował się więc aktywny i
# gwarantowanie kończył się błędem „Linia nie ma budżetu MD do przeniesienia",
# czyli komunikatem o danych do uzupełnienia w stanie, którego nie da się
# usunąć. U Polkomtela (jedyny klient kosztowy) nie było ŻADNEJ ścieżki
# wymiany osoby na zamówieniu kosztowym.


async def test_swap_works_on_a_cost_order_without_md_budget(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder, ClientOrderStatus

    client_id, contracts, names = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        is_cost_based=True,
        budget_amount=50000,
    )
    line_id = group["lines"][0]["id"]

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{line_id}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 900,
            "rate_revenue": 1500,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    new_line = resp.json()

    async with AsyncSessionLocal() as db:
        old = await db.get(ClientOrder, line_id)
        new = await db.get(ClientOrder, new_line["id"])
        # Domknięcie poprzednika lustrzane wobec trybu MD.
        assert old.end_date == _TODAY
        assert old.status == ClientOrderStatus.completed
        # Komplet NULL-i — inaczej `ck_client_orders_md_coherence` odrzuciłby
        # zapis, a częściowo wypełniona linia kłamałaby o budżecie.
        assert new.md_total is None
        assert new.md_remaining is None
        assert new.md_input_mode is None
        assert new.md_input_value is None
        # Stawki przechodzą — one są jedyną rzeczą, która się tu zmienia.
        assert new.md_rate_cost == Decimal("900.000000")
        assert new.md_rate_revenue == Decimal("1500.000000")
        assert new.predecessor_order_id == old.id


async def test_swap_on_cost_order_does_not_touch_the_shared_budget(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Pula jest wspólna — wymiana osoby nie jest wydatkiem ani zwrotem."""
    from app.core.database import AsyncSessionLocal
    from app.models.client_order_group import ClientOrderGroup

    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        is_cost_based=True,
        budget_amount=50000,
    )
    async with AsyncSessionLocal() as db:
        before = (await db.get(ClientOrderGroup, group["id"])).budget_remaining

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{group['lines'][0]['id']}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 900,
            "rate_revenue": 1500,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text

    async with AsyncSessionLocal() as db:
        after = (await db.get(ClientOrderGroup, group["id"])).budget_remaining
    assert after == before


async def test_swap_event_on_cost_order_does_not_mention_md_budget(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Historia ma opisywać to, co się stało — a nie pole, którego nie było."""
    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    _enable_cost(monkeypatch, client_id)
    group = await _create_group(
        app_client,
        app_auth_headers,
        client_id,
        [_cost_line(contracts[0])],
        is_cost_based=True,
        budget_amount=50000,
    )
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{group['lines'][0]['id']}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 900,
            "rate_revenue": 1500,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text

    history = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group['id']}/events",
        headers=app_auth_headers,
    )
    assert history.status_code == 200, history.text
    swapped = [
        e for e in history.json()["events"] if e["event_type"] == "zamiana_kontraktora"
    ]
    assert len(swapped) == 1
    assert "kosztowe" in swapped[0]["description"]
    assert "MD" not in swapped[0]["description"].replace("zł/MD", "")


async def test_swap_still_recalculates_md_on_a_normal_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Regresja: gałąź kosztowa nie może rozbroić przeliczenia w trybie MD.

    50 MD × 1200 zł = 60 000 zł; po zamianie na 1500 zł/MD musi wyjść 40 MD.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder

    client_id, contracts, _ = await _seed_client_with_contracts(2)
    _enable_multi(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_md_line(contracts[0])]
    )
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{group['lines'][0]['id']}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 900,
            "rate_revenue": 1500,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    async with AsyncSessionLocal() as db:
        new = await db.get(ClientOrder, resp.json()["id"])
    assert new.md_total == Decimal("40.000000")
    assert new.md_remaining == Decimal("40.000000")
