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


async def _seed_client_with_contracts(
    n_contracts: int = 2,
) -> tuple[int, list[int], list[str]]:
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


# ── Uprawnienia: delivery prowadzi obsadę zamówienia ────────────────────────


async def _seed_user(
    role_value: str, client_id: int | None = None
) -> tuple[int, str, str]:
    """Użytkownik danej roli (+ opcjonalne przypisanie DL do klienta)."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import DeliveryLeadClientAssignment
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    email = f"mo-{role_value}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"MO {role_value}",
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


async def test_assigned_delivery_lead_can_add_a_consultant_with_rates(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """To delivery układa obsadę zamówienia — musi móc dodać konsultanta.

    Zapis I odczyt naraz: rola, która zapisze stawkę i zobaczy w jej miejscu
    „—", nie może sprawdzić własnej pracy.
    """
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    _, email, password = await _seed_user("delivery_lead", client_id)
    dl_headers = await _headers_for(app_client, email, password)

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": "447",
            "start_date": _TODAY.isoformat(),
            "lines": [_line_payload(contracts[0])],
        },
        headers=dl_headers,
    )
    assert resp.status_code == 201, resp.text
    line = resp.json()["lines"][0]
    assert line["rate_cost"] == pytest.approx(1000.0), (
        "DL nie widzi stawki, którą zapisał"
    )
    assert line["rate_revenue"] == pytest.approx(1200.0)

    listing = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=dl_headers
    )
    assert listing.json()["groups"][0]["lines"][0]["rate_revenue"] == pytest.approx(
        1200.0
    )


async def test_unassigned_delivery_lead_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """DL BEZ przypisania do klienta nie dotknie ani zapisu, ani odczytu.

    To jest niezmiennik, na którym stoi cała bramka:
    ``_has_md_line_management_role`` sprawdza WYŁĄCZNIE rolę, a zawężenie do
    klienta robi trasa. Gdyby ten test padł, każdy Delivery Lead miałby stawki
    wszystkich klientów.
    """
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )

    _, email, password = await _seed_user("delivery_lead")  # bez client_id
    other_dl = await _headers_for(app_client, email, password)

    create = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": "448",
            "start_date": _TODAY.isoformat(),
            "lines": [_line_payload(contracts[0])],
        },
        headers=other_dl,
    )
    assert create.status_code == 403, create.text

    add_line = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
        json=_line_payload(contracts[0]),
        headers=other_dl,
    )
    assert add_line.status_code == 403, add_line.text

    swap = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{group['lines'][0]['id']}/swap",
        json={
            "contract_id": contracts[0],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": _TODAY.isoformat(),
        },
        headers=other_dl,
    )
    assert swap.status_code == 403, swap.text

    # Odczyt też — `_require_group_read` wymaga jawnego przypisania DL/TAC.
    read = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=other_dl
    )
    assert read.status_code == 403, read.text


async def test_who_sees_line_rates():
    """Widoczność stawek linii — dokładnie ten sam zbiór ról, co zapis.

    Sprawdzane na poziomie reguły, nie przez HTTP: TAC bez przypisania do
    klienta nie przeczyta nawet grupy, więc test przez API mierzyłby bramkę
    dostępu do klienta, a nie redakcję stawek.
    """
    from app.api.client_order_groups import _can_see_finance
    from app.models.user import UserRole

    class _StubUser:
        def __init__(self, role):
            self._role = role
            self.role = role
            self.roles = [role]

        def has_role(self, role):
            return self._role == role

        def has_any_role(self, *roles):
            return self._role in roles

        def get_all_roles(self):
            return [self._role]

    for role in (UserRole.admin, UserRole.delivery_lead, UserRole.finance):
        assert _can_see_finance(_StubUser(role)) is True, role
    for role in (UserRole.tac, UserRole.recruiter, UserRole.sourcer):
        assert _can_see_finance(_StubUser(role)) is False, role


async def test_legacy_order_finance_guard_is_untouched(
    app_client: AsyncClient, monkeypatch
):
    """Poluzowanie bramki dla linii MD NIE MOŻE otworzyć modułu zamówień.

    `rate_client`/`rate_candidate` w `client_orders.py` są interpretowane przez
    `Contract.rate_unit` i zostają admin-only. Gdyby ta asercja padła, znaczyłoby
    to, że nowa powierzchnia rozszczelniła starą.
    """
    from app.api.client_orders import _assert_order_finance_write_allowed
    from app.models.user import UserRole
    from fastapi import HTTPException

    class _StubUser:
        def __init__(self, role):
            self._role = role

        def has_role(self, role):
            return self._role == role

        def has_any_role(self, *roles):
            return self._role in roles

    for role in (UserRole.delivery_lead, UserRole.tac, UserRole.head_of_recruitment):
        with pytest.raises(HTTPException) as exc:
            _assert_order_finance_write_allowed(_StubUser(role), {"rate_client"})
        assert exc.value.status_code == 403, role

    _assert_order_finance_write_allowed(_StubUser(UserRole.admin), {"rate_client"})


async def test_head_of_recruitment_cannot_set_line_rates(monkeypatch):
    """HoR przechodzi przez DlAssignedOrAdmin globalnie, bez przypisania.

    Repo konsekwentnie trzyma go poza powierzchniami finansowymi (np.
    `/settings/clients-overview` jest admin-only właśnie z tego powodu), więc
    nie może ustawiać stawek mimo że przejdzie bramkę trasy.
    """
    from app.api.client_order_groups import _assert_line_finance_write_allowed
    from app.models.user import UserRole
    from fastapi import HTTPException

    class _StubUser:
        def __init__(self, role):
            self._role = role

        def has_role(self, role):
            return self._role == role

        def has_any_role(self, *roles):
            return self._role in roles

    with pytest.raises(HTTPException) as exc:
        _assert_line_finance_write_allowed(
            _StubUser(UserRole.head_of_recruitment), {"rate_cost"}
        )
    assert exc.value.status_code == 403

    for role in (UserRole.admin, UserRole.delivery_lead):
        _assert_line_finance_write_allowed(_StubUser(role), {"rate_cost"})


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
            _line_payload(
                contracts[1], rate_cost=800, rate_revenue=950, input_value=63
            ),
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


async def test_line_stays_editable_after_a_swap(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Każda kolejna edycja linii po zamianie kontraktora musi dać 200.

    Serializacja linii schodzi z poprzednika aż do kandydata
    (`predecessor_consultant_name`). Płaski `selectinload(predecessor)`
    ładował samego poprzednika i zostawiał tam leniwą relację, a w async
    SQLAlchemy leniwe doczytanie leci `MissingGreenlet` → 500 bez nagłówków
    CORS, czyli „Network Error" bez żadnej wskazówki. Wybuch następował już
    PO `commit()`: stawka zapisywała się w bazie, operator widział błąd bez
    treści i ponawiał — u BIK/Polkomtela/BNP codziennie.

    Dowód MUSI iść przez prawdziwego Postgresa. Na podstawionej sesji leniwe
    doczytanie nie ma jak wybuchnąć, więc test na mocku byłby zielony także
    przed poprawką — czyli nie dowodziłby niczego.
    """
    client_id, contracts, names = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)

    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    swap = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{group['lines'][0]['id']}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert swap.status_code == 201, swap.text
    successor_id = swap.json()["id"]

    patch = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{successor_id}",
        json={"rate_cost": 820},
        headers=app_auth_headers,
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["rate_cost"] == pytest.approx(820.0)
    # Poprzednik ma się nie tylko doczytać, ale i przedstawić — pusta nazwa
    # znaczyłaby, że łańcuch loaderów urwał się o jedno ogniwo za wcześnie.
    assert body["predecessor_consultant_name"] == names[0]


async def test_manual_adjustment_after_a_swap_survives_the_read(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Korekta MD na linii z poprzednikiem też musi się odczytać.

    Ta ścieżka wraca przez `db.refresh(line)`, a nie przez świeże zapytanie —
    gdyby odświeżenie gubiło loadery, `MissingGreenlet` wróciłby tędy mimo
    poprawionego zapytania wejściowego.
    """
    client_id, contracts, names = await _seed_client_with_contracts(2)
    _enable_for(monkeypatch, client_id)

    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    swap = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{group['lines'][0]['id']}/swap",
        json={
            "contract_id": contracts[1],
            "rate_cost": 800,
            "rate_revenue": 950,
            "swap_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert swap.status_code == 201, swap.text
    successor_id = swap.json()["id"]

    patch = await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines/{successor_id}",
        json={"md_remaining": 12},
        headers=app_auth_headers,
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["md_remaining"] == pytest.approx(12.0)
    assert body["predecessor_consultant_name"] == names[0]


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
    assert listing.json()["groups"][0]["lines"][0]["md_remaining"] == pytest.approx(
        35.0
    )

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


# ── Picker konsultantów: dwa źródła w jednej liście ─────────────────────────


async def _seed_person_with_contract(
    *, client_id: int, first: str, last: str, status_value: str = "active"
) -> tuple[int, int]:
    """Kandydat + kontrakt o wskazanym statusie. Zwraca (candidate_id, contract_id)."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=first,
            lastname=last,
            email=f"{uuid.uuid4().hex[:10]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)

        contract = Contract(
            candidate_id=cand.id,
            client_id=client_id,
            status=ContractStatus(status_value),
            start_date=_TODAY - timedelta(days=60),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return cand.id, contract.id


async def _seed_bare_client() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=f"OtherClient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client.id


async def _options(
    app_client: AsyncClient, headers: dict, client_id: int, **params
) -> dict:
    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups/consultant-options",
        params=params,
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_options_merge_two_sources_and_label_each_row(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Jedna lista, dwa źródła, każdy wiersz z etykietą pochodzenia."""
    surname = f"Zamowienie{uuid.uuid4().hex[:6]}"
    client_id, _, _ = await _seed_client_with_contracts(0)
    other_client = await _seed_bare_client()
    _enable_for(monkeypatch, client_id)

    ours, _ = await _seed_person_with_contract(
        client_id=client_id, first="Barbara", last=surname
    )
    theirs, _ = await _seed_person_with_contract(
        client_id=other_client, first="Adam", last=surname
    )

    data = await _options(app_client, app_auth_headers, client_id, q=surname)
    by_id = {o["candidate_id"]: o for o in data["options"]}

    assert by_id[ours]["source"] == "client_recruitment"
    assert by_id[ours]["source_label"] == "Rekrutacja u klienta"
    assert by_id[ours]["contract_id"] is not None
    assert by_id[theirs]["source"] == "nexus_base"
    assert by_id[theirs]["source_label"] == "Baza Nexus"
    # Osoba bez kontraktu u tego klienta nie ma czego wskazać — kontrakt
    # powstanie dopiero przy zapisie linii.
    assert by_id[theirs]["contract_id"] is None
    # Cała lista posortowana po imieniu, nie „najpierw źródło A".
    assert [o["candidate_id"] for o in data["options"]] == [theirs, ours]
    assert data["total"] == 2


async def test_options_never_show_the_same_person_twice(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Osoba z kontraktem u tego klienta NIE dubluje się jako „Baza Nexus"."""
    surname = f"Zamowienie{uuid.uuid4().hex[:6]}"
    client_id, _, _ = await _seed_client_with_contracts(0)
    other_client = await _seed_bare_client()
    _enable_for(monkeypatch, client_id)

    candidate_id, _ = await _seed_person_with_contract(
        client_id=client_id, first="Celina", last=surname
    )
    # Ta sama osoba pracuje równolegle u innego klienta — źródło B by ją
    # zwróciło, gdyby dedup szedł po kontrakcie zamiast po osobie.
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        db.add(
            Contract(
                candidate_id=candidate_id,
                client_id=other_client,
                status=ContractStatus.active,
                start_date=_TODAY - timedelta(days=10),
            )
        )
        await db.commit()

    data = await _options(app_client, app_auth_headers, client_id, q=surname)
    rows = [o for o in data["options"] if o["candidate_id"] == candidate_id]
    assert len(rows) == 1, f"osoba zdublowana w pickerze: {rows}"
    assert rows[0]["source"] == "client_recruitment"


async def test_options_skip_finished_consultants(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Baza Nexus to WYŁĄCZNIE aktywni; zakończony kontrakt nie wraca."""
    surname = f"Zamowienie{uuid.uuid4().hex[:6]}"
    client_id, _, _ = await _seed_client_with_contracts(0)
    other_client = await _seed_bare_client()
    _enable_for(monkeypatch, client_id)

    ended, _ = await _seed_person_with_contract(
        client_id=other_client, first="Damian", last=surname, status_value="ended"
    )
    ending, _ = await _seed_person_with_contract(
        client_id=other_client, first="Ewa", last=surname, status_value="ending"
    )

    data = await _options(app_client, app_auth_headers, client_id, q=surname)
    returned = {o["candidate_id"] for o in data["options"]}
    assert ended not in returned
    # `ending` = kontrakt < 30 dni do końca. To wciąż ktoś, kto pracuje, i
    # najbardziej oczywisty kandydat na kolejne zamówienie.
    assert ending in returned


async def test_options_search_matches_full_name_not_single_word(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """„Imię Nazwisko" zawęża do jednej osoby, samo imię — do wszystkich imion."""
    surname = f"Zamowienie{uuid.uuid4().hex[:6]}"
    twin_surname = f"Inne{uuid.uuid4().hex[:6]}"
    client_id, _, _ = await _seed_client_with_contracts(0)
    other_client = await _seed_bare_client()
    _enable_for(monkeypatch, client_id)

    wanted, _ = await _seed_person_with_contract(
        client_id=client_id, first="Filip", last=surname
    )
    namesake, _ = await _seed_person_with_contract(
        client_id=other_client, first="Filip", last=twin_surname
    )

    both = await _options(app_client, app_auth_headers, client_id, q="Filip", limit=500)
    ids = {o["candidate_id"] for o in both["options"]}
    assert {wanted, namesake} <= ids

    exact = await _options(
        app_client, app_auth_headers, client_id, q=f"Filip {surname}"
    )
    assert [o["candidate_id"] for o in exact["options"]] == [wanted]
    assert exact["total"] == 1


async def test_options_search_ignores_diacritics(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """„Lukasz Zolw" znajduje „Łukasz Żółw" — baza nie ma `unaccent`."""
    surname = f"Zolw{uuid.uuid4().hex[:6]}"
    client_id, _, _ = await _seed_client_with_contracts(0)
    _enable_for(monkeypatch, client_id)

    candidate_id, _ = await _seed_person_with_contract(
        client_id=client_id, first="Łukasz", last=f"Ż{surname}"
    )

    data = await _options(
        app_client, app_auth_headers, client_id, q=f"Lukasz Z{surname}"
    )
    assert [o["candidate_id"] for o in data["options"]] == [candidate_id]


async def test_options_report_how_many_were_cut(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Przycięta lista mówi, ilu jest naprawdę — ciche obcięcie czyta się jak komplet."""
    surname = f"Zamowienie{uuid.uuid4().hex[:6]}"
    client_id, _, _ = await _seed_client_with_contracts(0)
    _enable_for(monkeypatch, client_id)

    for first in ("Gustaw", "Halina", "Igor"):
        await _seed_person_with_contract(client_id=client_id, first=first, last=surname)

    data = await _options(app_client, app_auth_headers, client_id, q=surname, limit=2)
    assert len(data["options"]) == 2
    assert data["total"] == 3


async def test_options_are_empty_for_client_outside_allowlist(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """GET u klienta spoza modelu = pusta lista, nie odmowa (403 renderuje się jak awaria)."""
    client_id, _, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch)  # nikt nie jest objęty

    data = await _options(app_client, app_auth_headers, client_id)
    assert data == {"options": [], "total": 0}


# ── Dodanie osoby z bazy Nexus do zamówienia ────────────────────────────────


async def test_person_from_nexus_base_can_be_added_to_an_order(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Sedno ticketu: osoba bez rekrutacji u tego klienta wchodzi na zamówienie."""
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus
    from sqlalchemy import select

    surname = f"Zamowienie{uuid.uuid4().hex[:6]}"
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    other_client = await _seed_bare_client()
    _enable_for(monkeypatch, client_id)

    outsider, _ = await _seed_person_with_contract(
        client_id=other_client, first="Jolanta", last=surname
    )
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
        json={
            "candidate_id": outsider,
            "rate_cost": 900,
            "rate_revenue": 1100,
            "input_mode": "md",
            "input_value": 20,
            "start_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    line = resp.json()
    assert line["candidate_id"] == outsider
    assert line["consultant_name"] == f"Jolanta {surname}"

    # Linia MUSI wisieć na kontrakcie u TEGO klienta — na tym stoi skaner
    # wygasania, sync terminacji i MRR. Kontrakt jest `draft`, bo aktywacja ma
    # własny, walidowany cykl życia.
    async with AsyncSessionLocal() as db:
        contract = await db.scalar(
            select(Contract).where(Contract.id == line["contract_id"])
        )
        assert contract.client_id == client_id
        assert contract.candidate_id == outsider
        assert contract.status == ContractStatus.draft

    # Ta sama osoba jest już „u tego klienta", więc znika z bazy Nexus.
    options = await _options(app_client, app_auth_headers, client_id, q=surname)
    row = next(o for o in options["options"] if o["candidate_id"] == outsider)
    assert row["source"] == "client_recruitment"

    events = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group['id']}/events",
        headers=app_auth_headers,
    )
    added = [
        e for e in events.json()["events"] if e["event_type"] == "dodanie_konsultanta"
    ]
    assert any(e["payload"].get("contract_created") for e in added), (
        "historia zamówienia nie odnotowała, że kontrakt powstał przy dodaniu osoby"
    )


async def test_adding_by_candidate_id_reuses_an_existing_contract(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wskazanie osoby, która MA kontrakt u klienta, nie zakłada drugiego."""
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract
    from sqlalchemy import func, select

    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(Contract).where(Contract.id == contracts[0]))
        candidate_id = existing.candidate_id

    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
        json={
            "candidate_id": candidate_id,
            "rate_cost": 900,
            "rate_revenue": 1100,
            "input_mode": "md",
            "input_value": 20,
            "start_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["contract_id"] == contracts[0]

    async with AsyncSessionLocal() as db:
        total = await db.scalar(
            select(func.count(Contract.id)).where(
                Contract.client_id == client_id,
                Contract.candidate_id == candidate_id,
            )
        )
    assert total == 1, "powstał drugi, równoległy kontrakt u tego samego klienta"


async def test_line_needs_exactly_one_person_reference(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Ani zero, ani dwa wskazania osoby — inaczej jedno z pól ginie po cichu."""
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)

    base = {
        "rate_cost": 900,
        "rate_revenue": 1100,
        "input_mode": "md",
        "input_value": 20,
        "start_date": _TODAY.isoformat(),
    }
    for payload in ({}, {"contract_id": contracts[0], "candidate_id": 1}):
        resp = await app_client.post(
            f"/api/clients/{client_id}/order-groups",
            json={
                "order_number": f"445-{uuid.uuid4().hex[:4]}",
                "start_date": _TODAY.isoformat(),
                "lines": [{**base, **payload}],
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 422, resp.text


async def test_unknown_candidate_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contracts, _ = await _seed_client_with_contracts(1)
    _enable_for(monkeypatch, client_id)
    group = await _create_group(
        app_client, app_auth_headers, client_id, [_line_payload(contracts[0])]
    )

    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups/{group['id']}/lines",
        json={
            "candidate_id": 99_999_999,
            "rate_cost": 900,
            "rate_revenue": 1100,
            "input_mode": "md",
            "input_value": 20,
            "start_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 400, resp.text
