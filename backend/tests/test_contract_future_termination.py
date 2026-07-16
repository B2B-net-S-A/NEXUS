"""P0.7 — przyszłe wcześniejsze zakończenie NIE kończy kontraktu dziś (M5 PR-02).

Regresja produkcyjna: zarówno amendment ``early_termination`` jak i dedykowany
``/terminate`` ustawiały status ``ended`` natychmiast, niezależnie od daty
skutku. Konsultant znikał z aktywnych przed faktycznym końcem, a raporty/alerty/
billing dostawały przedwczesny stan.

Fix: status wyliczany przez ``_status_after_end_date_change`` z daty końca —
future → zostaje active/ending, dopiero cron materializuje ``ended`` w dniu
zakończenia. Testy seedują WŁASNY kontrakt (nie ``_pick_parties`` z silent
return), więc zawsze wykonują asercję biznesową.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

_TODAY = date.today()


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
            start_date=_TODAY - timedelta(days=30),
            end_date=_TODAY + timedelta(days=end_offset_days),
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


async def test_future_early_termination_amendment_keeps_active(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_active_contract()
    early_end = _TODAY + timedelta(days=30)
    r = await app_client.post(
        f"/api/contracts/{cid}/amendments",
        json={
            "amendment_type": "early_termination",
            "effective_date": _TODAY.isoformat(),
            "new_end_date": early_end.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 201, r.text
    assert r.json()["new_values"]["status"] == "active"

    after = await _status(app_client, app_auth_headers, cid)
    assert after["status"] == "active", "future early termination ended it today!"
    assert after["end_date"] == early_end.isoformat()


async def test_today_early_termination_amendment_ends(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_active_contract()
    r = await app_client.post(
        f"/api/contracts/{cid}/amendments",
        json={
            "amendment_type": "early_termination",
            "effective_date": _TODAY.isoformat(),
            "new_end_date": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 201, r.text
    after = await _status(app_client, app_auth_headers, cid)
    assert after["status"] == "ended"


# ── Dedicated /terminate ─────────────────────────────────────────────────────


async def test_future_terminate_keeps_active(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid = await _seed_active_contract()
    future = _TODAY + timedelta(days=30)
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
    assert after["status"] in ("active", "ending"), (
        f"future terminate ended it today: {after['status']}"
    )


async def test_today_terminate_ends(app_client: AsyncClient, app_auth_headers: dict):
    cid = await _seed_active_contract()
    r = await app_client.post(
        f"/api/contracts/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": _TODAY.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    after = await _status(app_client, app_auth_headers, cid)
    assert after["status"] == "ended"
