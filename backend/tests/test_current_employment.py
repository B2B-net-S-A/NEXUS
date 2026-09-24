"""„Obecnie pracuje u klienta" wyprowadzone z umów (17.09.2026, D9).

Reguła: umowa trwa, gdy ``status ∈ {active, ending}`` i start jest pusty albo
nie później niż dziś. KONIEC rozstrzyga status (umowa B2B bezterminowa),
``end_date`` nie jest czytane.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.models.contract import ContractStatus
from app.services.current_employment import (
    current_employment_client_ids,
    is_live_contract,
)
from app.core.scheduling import business_today

TODAY = date(2026, 9, 17)


@pytest.mark.parametrize(
    "status, start, expected",
    [
        (ContractStatus.active, None, True),
        (ContractStatus.active, TODAY, True),
        (ContractStatus.ending, TODAY - timedelta(days=30), True),
        (ContractStatus.active, TODAY + timedelta(days=1), False),
        (ContractStatus.draft, None, False),
        (ContractStatus.ended, TODAY - timedelta(days=30), False),
    ],
)
def test_is_live_contract(status, start, expected):
    contract = SimpleNamespace(status=status, start_date=start)
    assert is_live_contract(contract, TODAY) is expected


def test_end_date_in_the_past_does_not_end_a_live_contract():
    """Status decides the end — a stale `end_date` on an active contract."""
    contract = SimpleNamespace(
        status=ContractStatus.active,
        start_date=TODAY - timedelta(days=400),
        end_date=TODAY - timedelta(days=10),
    )
    assert is_live_contract(contract, TODAY) is True


async def _seed() -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client_a = Client(name=f"CurEmpA-{tag}")
        client_b = Client(name=f"CurEmpB-{tag}")
        live = Candidate(name="Live", lastname=f"CurEmp-{tag}")
        future = Candidate(name="Future", lastname=f"CurEmp-{tag}")
        idle = Candidate(name="Idle", lastname=f"CurEmp-{tag}")
        db.add_all([client_a, client_b, live, future, idle])
        await db.flush()
        today = business_today()
        db.add_all(
            [
                Contract(
                    candidate_id=live.id,
                    client_id=client_a.id,
                    start_date=today - timedelta(days=60),
                    # stale end date — status still says it runs
                    end_date=today - timedelta(days=1),
                    status=ContractStatus.active,
                ),
                Contract(
                    candidate_id=live.id,
                    client_id=client_b.id,
                    start_date=None,
                    status=ContractStatus.ending,
                ),
                Contract(
                    candidate_id=future.id,
                    client_id=client_a.id,
                    start_date=today + timedelta(days=10),
                    status=ContractStatus.active,
                ),
                Contract(
                    candidate_id=idle.id,
                    client_id=client_a.id,
                    start_date=today - timedelta(days=300),
                    status=ContractStatus.ended,
                ),
            ]
        )
        await db.commit()
        return {
            "a": client_a.id,
            "b": client_b.id,
            "live": live.id,
            "future": future.id,
            "idle": idle.id,
        }


async def test_current_employment_client_ids_from_live_contracts():
    from app.core.database import AsyncSessionLocal

    w = await _seed()
    async with AsyncSessionLocal() as db:
        out = await current_employment_client_ids(
            db, [w["live"], w["future"], w["idle"]], today=business_today()
        )
    assert out == {w["live"]: {w["a"], w["b"]}, w["future"]: set(), w["idle"]: set()}


async def test_current_employment_client_ids_scoped_to_one_client():
    from app.core.database import AsyncSessionLocal

    w = await _seed()
    async with AsyncSessionLocal() as db:
        out = await current_employment_client_ids(
            db, [w["live"], w["idle"]], client_id=w["b"], today=business_today()
        )
    assert out == {w["live"]: {w["b"]}, w["idle"]: set()}


async def test_current_employment_client_ids_empty_input():
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        assert await current_employment_client_ids(db, [], today=business_today()) == {}
