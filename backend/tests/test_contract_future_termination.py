"""P0.7 — przyszłe wcześniejsze zakończenie NIE kończy kontraktu dziś (M5 PR-02).

Regresja produkcyjna: zarówno amendment ``early_termination`` jak i dedykowany
``/terminate`` ustawiały status ``ended`` natychmiast, niezależnie od daty
skutku. Konsultant znikał z aktywnych przed faktycznym końcem, a raporty/alerty/
billing dostawały przedwczesny stan.

Fix: status wyliczany z daty końca — przyszła albo dzisiejsza data →
„Kończący się” (od 23.09.2026, ticket „Zakończenie współpracy — obowiązkowy
formularz”: do dnia zakończenia projektu włącznie), dopiero cron materializuje
``ended`` dzień po dacie zakończenia. Testy seedują WŁASNY kontrakt (nie ``_pick_parties`` z silent
return), więc zawsze wykonują asercję biznesową.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today


async def _seed_active_contract(end_offset_days: int = 90) -> int:
    """Aktywny kontrakt z end_date w przyszłości; zwraca id."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Term",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"term-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"TermClient-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.commit()
        await db.refresh(cand)
        await db.refresh(client)
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=30),
            end_date=business_today() + timedelta(days=end_offset_days),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(contract)
        await db.commit()
        await db.refresh(contract)
        return contract.id


async def _status(app_client: AsyncClient, headers: dict, cid: int) -> dict:
    r = await app_client.get(f"/api/contracts/{cid}", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


# ── Amendment early_termination ──────────────────────────────────────────────


@pytest.mark.parametrize("days_ahead", [0, 30])
async def test_early_termination_amendment_is_refused_in_favour_of_the_window(
    app_client: AsyncClient, app_auth_headers: dict, days_ahead: int
):
    """Audyt 24.09 (S5): aneks „wcześniejsze zakończenie” przez API omijał
    okno „Zakończ współpracę” (powód, koniec projektu, rozwiązanie umowy,
    migawka do cofnięcia). Odmowa 409 ``termination_required`` bez zapisu."""
    cid = await _seed_active_contract()
    before = await _status(app_client, app_auth_headers, cid)
    r = await app_client.post(
        f"/api/contracts/{cid}/amendments",
        json={
            "amendment_type": "early_termination",
            "effective_date": business_today().isoformat(),
            "new_end_date": (business_today() + timedelta(days=days_ahead)).isoformat(),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["reason"] == "termination_required"

    after = await _status(app_client, app_auth_headers, cid)
    assert after["status"] == before["status"]
    assert after["end_date"] == before["end_date"]


# ── Dedicated /terminate ─────────────────────────────────────────────────────


async def test_future_terminate_keeps_active(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_active_contract()
    future = business_today() + timedelta(days=30)
    r = await app_client.post(
        f"/api/contracts/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": future.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    after = await _status(app_client, app_auth_headers, cid)
    assert after["status"] == "ending", (
        f"future terminate ended it today: {after['status']}"
    )


async def test_today_terminate_is_ending_until_tomorrow(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_active_contract()
    r = await app_client.post(
        f"/api/contracts/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": business_today().isoformat(),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    after = await _status(app_client, app_auth_headers, cid)
    assert after["status"] == "ending"


async def test_past_terminate_ends_immediately(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_active_contract()
    r = await app_client.post(
        f"/api/contracts/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": (business_today() - timedelta(days=1)).isoformat(),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    after = await _status(app_client, app_auth_headers, cid)
    assert after["status"] == "ended"
