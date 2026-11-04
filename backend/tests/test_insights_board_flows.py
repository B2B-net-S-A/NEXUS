"""Insights → Firma: ruch konsultantów i popyt (`/api/insights/board/flows`).

„318 konsultantów” nie mówi, czy firma rośnie (Artur, 22.10.2026). Ruch
liczą te same funkcje co API integracyjne i tabele rok do roku
(`contract_flows`, `departure_day`), kończące się bez kontynuacji — reguła
pigułki „Kończące się 30d” (`ending_without_successor`).

Baza testowa jest wspólna i nieczyszczona, a `compute_board_flows` liczy całą
firmę. Rok 2058 nie jest zarezerwowany: `test_finance_order_changes.py` losuje
dni z lat 2058–2061 (`_far_day`) i zakłada tam kontrakty, a o tym, czy oba
pliki trafią do jednego shardu, decyduje kolejność plików (#2723 wypadł przez
to z kolejki 27.10.2026). Dlatego test porównuje wynik przed zasiewem i po
nim — liczą się tylko jego własne wiersze, cudze się odejmują. Shard to jeden
proces bez xdist, więc między odczytami nikt inny nie pisze.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.analytics.periods import resolve_period
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import (
    Contract,
    ContractStatus,
    ContractTerminationReason,
    RateUnit,
)
from app.models.job import Job, JobStatus, RemotePolicy
from app.models.user import User, UserRole
from app.services.insights_board_flows import compute_board_flows

_YEAR = 2058


async def _seed() -> dict[str, Any]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"Flows-{tag}")
        db.add(cli)
        await db.flush()
        cands = [
            Candidate(
                name=f"Ruch{i}",
                lastname=f"Test-{tag}",
                email=f"flows-{tag}-{i}@example.com",
            )
            for i in range(5)
        ]
        db.add_all(cands)
        await db.flush()

        def contract(i: int, start: date, end: date | None, status, **kw) -> Contract:
            c = Contract(
                candidate_id=cands[i].id,
                client_id=cli.id,
                start_date=start,
                end_date=end,
                rate_client=Decimal("150"),
                rate_candidate=Decimal("120"),
                rate_unit=RateUnit.hourly,
                rate_client_currency="PLN",
                rate_candidate_currency="PLN",
                currency="PLN",
                status=status,
                **kw,
            )
            db.add(c)
            return c

        # Start w marcu.
        contract(0, date(_YEAR, 3, 10), None, ContractStatus.active)
        # Zejście w marcu — rezygnacja konsultanta.
        contract(
            1,
            date(_YEAR - 1, 6, 1),
            date(_YEAR, 3, 20),
            ContractStatus.ended,
            termination_reason=ContractTerminationReason.consultant_resigned,
        )
        # Zejście w lutym — poprzedni odcinek.
        contract(2, date(_YEAR - 1, 6, 1), date(_YEAR, 2, 15), ContractStatus.ended)
        # Aktywny, zamówienie kończy się 15.04 bez kontynuacji.
        ending = contract(3, date(_YEAR - 1, 1, 1), None, ContractStatus.active)
        # Aktywny, zamówienie kończy się 10.04, ale jest następne.
        extended = contract(4, date(_YEAR - 1, 1, 1), None, ContractStatus.active)
        await db.flush()

        def order(c: Contract, start: date, end: date) -> None:
            db.add(
                ClientOrder(
                    client_id=cli.id,
                    contract_id=c.id,
                    title=f"Z-{tag}-{c.id}-{start}",
                    status=ClientOrderStatus.active,
                    start_date=start,
                    end_date=end,
                    rate_client=Decimal("150.000"),
                    rate_unit=RateUnit.hourly,
                )
            )

        order(ending, date(_YEAR, 1, 1), date(_YEAR, 4, 15))
        order(extended, date(_YEAR, 1, 1), date(_YEAR, 4, 10))
        order(extended, date(_YEAR, 4, 11), date(_YEAR, 12, 31))
        db.add(
            Job(
                title=f"Flows {tag}",
                location="Warszawa",
                status=JobStatus.published,
                remote_policy=RemotePolicy.hybrid,
                client_id=cli.id,
                created_at=datetime(_YEAR, 3, 5, 9, tzinfo=timezone.utc),
            )
        )
        await db.commit()
    return {}


async def _march_flows() -> dict[str, Any]:
    period = resolve_period("month", anchor=date(_YEAR, 3, 1))
    async with AsyncSessionLocal() as db:
        return await compute_board_flows(
            db,
            period,
            today=date(_YEAR, 3, 31),
            now=datetime(_YEAR, 4, 1, 12, tzinfo=timezone.utc),
        )


def _added(after: dict[str, int], before: dict[str, int]) -> dict[str, int]:
    return {key: after[key] - before[key] for key in after}


@pytest.mark.asyncio
async def test_flows_count_starts_departures_and_contracts_ending_without_continuation():
    before = await _march_flows()
    await _seed()
    result = await _march_flows()
    assert _added(result["consultants"], before["consultants"]) == {
        "starts": 1,
        "ends": 1,
        "resignations": 1,
        "net": 0,
    }
    # Poprzedni odcinek = cały luty (marzec zamknięty).
    assert (
        result["previous_consultants"]["ends"] - before["previous_consultants"]["ends"]
        == 1
    )
    assert result["previous_window"] == {
        "from": f"{_YEAR}-02-01",
        "to": f"{_YEAR}-02-28",
    }
    assert result["ending_without_continuation"]["days"] == 30
    assert (
        result["ending_without_continuation"]["contracts"]
        - before["ending_without_continuation"]["contracts"]
        == 1
    )
    assert result["jobs"]["new"] - before["jobs"]["new"] == 1
    assert isinstance(result["jobs"]["open"], int)


async def _login(client: AsyncClient, role: UserRole) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"flows-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Flows"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                name=f"Flows {unique}",
                password_hash=hash_password(password),
                role=role,
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def fx_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.admin, UserRole.board])
async def test_flows_open_for_money_readers(fx_client: AsyncClient, role: UserRole):
    headers = await _login(fx_client, role)
    resp = await fx_client.get("/api/insights/board/flows", headers=headers)
    assert resp.status_code == 200, resp.text
    assert set(resp.json()["consultants"]) == {"starts", "ends", "resignations", "net"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role", [UserRole.head_of_recruitment, UserRole.recruiter, UserRole.delivery_lead]
)
async def test_flows_closed_like_the_cockpit(fx_client: AsyncClient, role: UserRole):
    headers = await _login(fx_client, role)
    resp = await fx_client.get("/api/insights/board/flows", headers=headers)
    assert resp.status_code == 403, resp.text
