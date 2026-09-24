"""Kwoty zamówienia kosztowego są po tej samej stronie linii co stawki linii.

``_line_to_read`` świadomie zeruje ``rate_cost`` / ``rate_revenue`` /
``input_value`` dla ról bez ``VIEW_FINANCE``, a liczba MD zostaje — pasek
zużycia jest informacją operacyjną. Kwota zamówienia i sumy zafakturowane
wychodziły jednak bezwarunkowo, więc redakcja stawek dawała się obejść
arytmetyką: ``budget_amount`` podzielone przez jawne ``md_total`` odtwarza
dokładnie tę stawkę, którą serwer przed chwilą schował.

Head of Recruitment jest tu przypadkiem najostrzejszym: przechodzi
``_require_group_read`` GLOBALNIE, bez przypisania do klienta, więc widział te
kwoty u każdego klienta wielo-konsultantowego.
"""

from __future__ import annotations

import io
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from app.core.scheduling import business_today

pytestmark = pytest.mark.asyncio

_TODAY = business_today()


def _enable(monkeypatch, client_id: int) -> None:
    from app.services import cost_orders as co
    from app.services import multi_consultant_orders as mco

    monkeypatch.setattr(
        mco, "multi_consultant_client_ids", lambda: frozenset({client_id})
    )
    monkeypatch.setattr(co, "cost_order_client_ids", lambda: frozenset({client_id}))


def _sheet(order_number: str, name: str, invoice: float) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Imię i nazwisko", "Ilość MD", "Uwagi", "Faktura"])
    ws.append([name, 10, f"SAP {order_number}", invoice])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _seed_client_with_contract() -> tuple[int, int, str]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"BudgetRedaction-{suffix}")
        cand = Candidate(
            name="Kosz",
            lastname=f"Towy-{suffix}",
            email=f"budget-{suffix}@example.com",
        )
        db.add_all([client, cand])
        await db.commit()
        await db.refresh(client)
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
        return client.id, contract.id, f"{cand.name} {cand.lastname}"


async def _headers_for_role(
    app_client: AsyncClient, role_value: str, client_id: int
) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.team_structure import ClientTacAssignment
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    email = f"budget-{role_value}-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Budget {role_value}",
            role=UserRole(role_value),
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        # TAC dochodzi do zamówień wyłącznie przez jawne przypisanie do
        # klienta; Head of Recruitment przechodzi guard globalnie i przypisania
        # nie potrzebuje — to właśnie czyni go przypadkiem najostrzejszym.
        if role_value == "tac":
            db.add(ClientTacAssignment(client_id=client_id, tac_user_id=user.id))
            await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _create_cost_group(
    app_client: AsyncClient, headers: dict, client_id: int, contract_id: int
) -> dict:
    # Numer bez myślnika — ścieżka kosztowa importu dopasowuje wiersz po
    # numerze zamówienia wyłuskanym z kolumny „Uwagi".
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"450{uuid.uuid4().int % 10**7:07d}",
            "start_date": (_TODAY - timedelta(days=10)).isoformat(),
            "is_cost_based": True,
            "budget_amount": 500000,
            "lines": [
                {
                    "contract_id": contract_id,
                    "rate_cost": 1000,
                    "rate_revenue": 1200,
                    "start_date": (_TODAY - timedelta(days=10)).isoformat(),
                }
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _import_invoice(
    app_client: AsyncClient, group: dict, name: str, amount: float
) -> None:
    """Jedna faktura, żeby `invoiced_total` niosło liczbę, a nie None."""
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:8]
    email = f"budget-import-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Budget import {suffix}",
                role=UserRole.finance,
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    resp = await app_client.post(
        "/api/md-consumption/imports",
        files={
            "file": (
                "raport.xlsx",
                _sheet(group["order_number"], name, amount),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"period_month": _TODAY.strftime("%Y-%m")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text


async def _group_row(
    app_client: AsyncClient, headers: dict, client_id: int, group_id: int
) -> dict:
    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return next(g for g in resp.json()["groups"] if g["id"] == group_id)


async def test_admin_still_sees_the_budget(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Bramka nie może zgasić kwot roli, która ma je widzieć."""
    client_id, contract_id, name = await _seed_client_with_contract()
    _enable(monkeypatch, client_id)
    group = await _create_cost_group(
        app_client, app_auth_headers, client_id, contract_id
    )
    await _import_invoice(app_client, group, name, 120000)

    body = await _group_row(app_client, app_auth_headers, client_id, group["id"])
    assert body["budget_amount"] == pytest.approx(500000.0)
    assert body["budget_remaining"] == pytest.approx(380000.0)
    assert body["budget_used"] == pytest.approx(120000.0)
    assert body["lines"][0]["invoiced_total"] == pytest.approx(120000.0)


async def test_tcm_gets_no_budget_amounts(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contract_id, name = await _seed_client_with_contract()
    _enable(monkeypatch, client_id)
    group = await _create_cost_group(
        app_client, app_auth_headers, client_id, contract_id
    )
    await _import_invoice(app_client, group, name, 120000)
    headers = await _headers_for_role(app_client, "talent_community_manager", client_id)

    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = next(g for g in resp.json()["groups"] if g["id"] == group["id"])

    # Stawki linii — redakcja, która działała od początku.
    assert body["lines"][0]["rate_cost"] is None
    assert body["lines"][0]["rate_revenue"] is None
    # Kwoty grupy i sumy zafakturowane — ta sama strona linii.
    for field in (
        "budget_amount",
        "budget_used",
        "budget_remaining",
        "budget_manual_adjustment",
    ):
        assert body[field] is None, f"{field} wyciekło do roli bez VIEW_FINANCE"
    assert body["lines"][0]["invoiced_total"] is None
    assert body["lines"][0]["unsettled_total"] is None
    # Liczby MD i stan operacyjny zostają — pasek zużycia nie jest kwotą.
    assert body["is_cost_based"] is True
    assert body["active_consultants"] == 1


@pytest.mark.parametrize("role_value", ["head_of_recruitment", "tac"])
async def test_recruitment_roles_cannot_enter_delivery_order_groups(
    app_client: AsyncClient,
    app_auth_headers: dict,
    monkeypatch,
    role_value: str,
):
    client_id, contract_id, _name = await _seed_client_with_contract()
    _enable(monkeypatch, client_id)
    await _create_cost_group(app_client, app_auth_headers, client_id, contract_id)
    headers = await _headers_for_role(app_client, role_value, client_id)

    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "section_access_denied"


# ── Faza B: sumy umowy MD per osoba ─────────────────────────────────────────


async def _create_md_group(
    app_client: AsyncClient, headers: dict, client_id: int, contract_id: int
) -> dict:
    resp = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"CeZ-{uuid.uuid4().hex[:6]}",
            "start_date": (_TODAY - timedelta(days=10)).isoformat(),
            "order_type": "md",
            "md_budget_mode": "per_person",
            "lines": [
                {
                    "contract_id": contract_id,
                    "rate_cost": 1000,
                    "rate_revenue": 1200,
                    "input_mode": "md",
                    "input_value": 190,
                    "optional_md": 170,
                    "start_date": (_TODAY - timedelta(days=10)).isoformat(),
                }
            ],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_contract_value_is_redacted_but_md_scope_stays(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Wartość umowy w PLN = liczba MD × stawka, więc idzie z redakcją stawek."""
    client_id, contract_id, _name = await _seed_client_with_contract()
    _enable(monkeypatch, client_id)
    group = await _create_md_group(app_client, app_auth_headers, client_id, contract_id)
    line = group["lines"][0]
    put = await app_client.put(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{line['id']}/consumptions/2026-07",
        json={"md_reported": 154, "status": "accepted"},
        headers=app_auth_headers,
    )
    assert put.status_code == 200, put.text

    admin = await _group_row(app_client, app_auth_headers, client_id, group["id"])
    assert admin["contract_value_pln"] == pytest.approx(360 * 1200)
    assert admin["used_value_pln"] == pytest.approx(154 * 1200)

    headers = await _headers_for_role(app_client, "talent_community_manager", client_id)
    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = next(g for g in resp.json()["groups"] if g["id"] == group["id"])
    assert body["contract_value_pln"] is None
    assert body["used_value_pln"] is None
    # Liczby MD są operacyjne — zostają razem z podziałem na podstawę i opcję.
    assert body["md_positions_total"] == 360
    assert body["md_used_total"] == 154
    assert body["lines"][0]["md_total"] == 190
    assert body["lines"][0]["md_optional_total"] == 170
    assert body["lines"][0]["md_base_used"] == 154
    assert body["lines"][0]["md_optional_used"] == 0
    assert body["lines"][0]["rate_revenue"] is None


# ── Audyt 22.09 r2 (FIN-MD-05): kwoty w opisie historii ─────────────────────


def test_redact_amounts_keeps_md_and_dates():
    from app.api.client_order_groups import _redact_amounts

    text = (
        "Zamiana kontraktora 2026-09-01: Jan (1320 zł/MD, pozostało 30 MD) → "
        "Anna (950 zł/MD, 41,684 MD). Wartość pozostała bez zmian: 39 600,50 zł."
    )
    redacted = _redact_amounts(text)
    assert "zł" not in redacted
    assert "30 MD" in redacted and "41,684 MD" in redacted
    assert "2026-09-01" in redacted


async def test_history_description_hides_amounts_without_finance(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    client_id, contract_id, _name = await _seed_client_with_contract()
    _enable(monkeypatch, client_id)
    group = await _create_md_group(app_client, app_auth_headers, client_id, contract_id)
    await app_client.patch(
        f"/api/clients/{client_id}/order-groups/{group['id']}"
        f"/lines/{group['lines'][0]['id']}",
        json={"rate_cost": 1100},
        headers=app_auth_headers,
    )

    async def _no_finance(*_args, **_kwargs):
        return False

    monkeypatch.setattr("app.api.client_order_groups._can_see_finance", _no_finance)
    resp = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group['id']}/events",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    descriptions = " ".join(e["description"] for e in resp.json()["events"])
    assert "zł" not in descriptions and "PLN" not in descriptions
    assert "MD" in descriptions
