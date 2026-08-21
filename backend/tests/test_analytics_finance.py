"""Testy finansów Analytics (plan PR 6).

Pokrywa: konwersję FX (PLN + kurs raportowy; brak kursu = unavailable,
NIGDY 1:1), prawdziwą arytmetykę miesięcy (28/29/30/31), bench/utilization,
filled_at ustawiane RAZ, financial_adjustments (draft→approved, immutable,
RBAC: Finance/Admin, bez Delivery Lead).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.analytics.metrics import _month_starts_back, _sum_finance
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.fx_rate import FxRate
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


def test_month_starts_true_calendar_arithmetic():
    """28/29/30/31 dni — początki miesięcy bez timedelta(30)."""
    months = _month_starts_back(4, today=date(2028, 3, 15))  # 2028 = przestępny
    assert months == [
        date(2027, 12, 1),
        date(2028, 1, 1),
        date(2028, 2, 1),
        date(2028, 3, 1),
    ]
    over_year = _month_starts_back(13, today=date(2026, 1, 31))
    assert over_year[0] == date(2025, 1, 1)
    assert over_year[-1] == date(2026, 1, 1)


def _priced_contract(
    rate: str | None, margin: str | None, currency: str = "PLN"
) -> Contract:
    """Nieprzypisana umowa o zadanej miesięcznej stawce klienta i marży.

    Prawdziwy ``Contract``, nie duck-type z dwiema właściwościami: ``_sum_finance``
    rozstrzyga stawkę na dzień odniesienia przez ``effective_rate_fields``, więc
    atrapa przestała odpowiadać na pytania, które ta ścieżka zadaje. Obiekt
    transient ma puste kolekcje harmonogramów, więc resolver schodzi do kolumn —
    dokładnie jak umowa bez zaplanowanych kroków stawkowych.
    """
    client_rate = Decimal(rate) if rate is not None else None
    candidate_rate = (
        client_rate - Decimal(margin)
        if client_rate is not None and margin is not None
        else None
    )
    return Contract(
        rate_client=client_rate,
        rate_candidate=candidate_rate,
        rate_unit=RateUnit.monthly,
        currency=currency,
    )


async def _seed_rate(currency: str, rate: str, on: date) -> None:
    async with AsyncSessionLocal() as db:
        exists = await db.scalar(
            select(FxRate).where(
                FxRate.currency == currency, FxRate.effective_date == on
            )
        )
        if exists is None:
            db.add(
                FxRate(
                    effective_date=on,
                    currency=currency,
                    rate_to_pln=Decimal(rate),
                    source="test",
                )
            )
            await db.commit()


async def test_sum_finance_pln_only():
    async with AsyncSessionLocal() as db:
        data, warnings, flag = await _sum_finance(
            db,
            [_priced_contract("10000", "3000"), _priced_contract("5000.50", "1000.25")],
        )
    assert flag == "complete"
    assert data["mrr"] == "15000.50"
    assert data["monthly_margin"] == "4000.25"
    assert data["currency"] == "PLN"


async def test_sum_finance_fx_conversion_with_rate():
    await _seed_rate("EUR", "4.000000", date(2026, 1, 2))
    async with AsyncSessionLocal() as db:
        data, warnings, flag = await _sum_finance(
            db,
            [_priced_contract("1000", "100", "EUR"), _priced_contract("1000", "100")],
            on=date(2026, 1, 10),
        )
    assert flag == "complete"
    # 1000 EUR × 4.0 + 1000 PLN = 5000 PLN
    assert data["mrr"] == "5000.00"
    assert any("kursie raportowym" in w for w in warnings)


async def test_sum_finance_missing_rate_is_unavailable_never_nominal():
    """Waluta bez kursu ⇒ unavailable; kwota NIE wchodzi 1:1 (plan §3.4)."""
    async with AsyncSessionLocal() as db:
        data, warnings, flag = await _sum_finance(
            db,
            [_priced_contract("1000", "100", "XXX"), _priced_contract("2000", "200")],
        )
    assert flag == "unavailable"
    assert data["mrr"] == "2000.00", "kwota XXX nie może wejść nominalnie"
    assert any("Brak kursu" in w for w in warnings)


# ── filled_at + financial_adjustments przez API ─────────────────────────────


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"fin-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!F"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"Fin {role.value}",
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    return email, password


@pytest_asyncio.fixture
async def fin_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_adjustments_rbac_and_immutability(fin_client: AsyncClient):
    email_admin, pass_admin = await _seed_user(UserRole.admin)
    email_finance, pass_finance = await _seed_user(UserRole.finance)
    email_dl, pass_dl = await _seed_user(UserRole.delivery_lead)
    email_tac, pass_tac = await _seed_user(UserRole.tac)
    h_admin = await _login(fin_client, email_admin, pass_admin)
    h_finance = await _login(fin_client, email_finance, pass_finance)
    h_dl = await _login(fin_client, email_dl, pass_dl)
    h_tac = await _login(fin_client, email_tac, pass_tac)

    payload = {
        "effective_month": "2026-07-01",
        "kind": "discount",
        "amount": "-1500.50",
        "currency": "pln",
        "description": "Rabat testowy dla klienta X",
    }

    # write: DL nie może, Finance może
    denied = await fin_client.post(
        "/api/financial-adjustments", json=payload, headers=h_dl
    )
    assert denied.status_code == 403
    created = await fin_client.post(
        "/api/financial-adjustments", json=payload, headers=h_finance
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "draft"
    assert body["amount"] == "-1500.50"
    assert body["currency"] == "PLN"
    adj_id = body["id"]

    # read: Finance/Admin tak, DL i TAC nie
    assert (
        await fin_client.get("/api/financial-adjustments", headers=h_finance)
    ).status_code == 200
    assert (
        await fin_client.get("/api/financial-adjustments", headers=h_admin)
    ).status_code == 200
    assert (
        await fin_client.get("/api/financial-adjustments", headers=h_dl)
    ).status_code == 403
    assert (
        await fin_client.get("/api/financial-adjustments", headers=h_tac)
    ).status_code == 403

    # Finance przygotowuje korektę, ale zatwierdza ją wyłącznie Admin.
    deny_approve = await fin_client.post(
        f"/api/financial-adjustments/{adj_id}/approve", headers=h_dl
    )
    assert deny_approve.status_code == 403
    deny_finance_approve = await fin_client.post(
        f"/api/financial-adjustments/{adj_id}/approve", headers=h_finance
    )
    assert deny_finance_approve.status_code == 403
    approved = await fin_client.post(
        f"/api/financial-adjustments/{adj_id}/approve", headers=h_admin
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by"] != approved.json()["created_by"]
    again = await fin_client.post(
        f"/api/financial-adjustments/{adj_id}/approve", headers=h_admin
    )
    assert again.status_code == 409

    # brak PATCH/DELETE w ogóle (immutable audit trail)
    assert (
        await fin_client.patch(
            f"/api/financial-adjustments/{adj_id}", json={}, headers=h_admin
        )
    ).status_code in (404, 405)
    assert (
        await fin_client.delete(f"/api/financial-adjustments/{adj_id}", headers=h_admin)
    ).status_code in (404, 405)


async def test_bench_counts_historical_without_active():
    """Bench = miał kontrakt (date-effective), dziś bez aktywnego."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bench Client {unique}")
        db.add(client)
        await db.flush()
        bench_cand = Candidate(name="Ben", lastname=f"Ch-{unique}")
        active_cand = Candidate(name="Act", lastname=f"Ive-{unique}")
        db.add_all([bench_cand, active_cand])
        await db.flush()
        db.add(
            Contract(
                candidate_id=bench_cand.id,
                client_id=client.id,
                status=ContractStatus.ended,
                start_date=date(2025, 1, 1),
                end_date=date(2025, 6, 30),
            )
        )
        db.add(
            Contract(
                candidate_id=active_cand.id,
                client_id=client.id,
                status=ContractStatus.active,
                start_date=date(2026, 1, 1),
                end_date=None,
            )
        )
        await db.commit()

    from app.analytics.metrics import _bench_and_utilization

    async with AsyncSessionLocal() as db:
        result = await _bench_and_utilization(db)
    assert result["bench"] >= 1
    assert result["active_consultants"] >= 1
    assert result["utilization_pct"] is None or 0 <= result["utilization_pct"] <= 100
