"""Tests for the effective-dated framework-rate schedule (migracja 0165).

Mirror of ``test_contract_client_rate_schedule`` — the framework rate ("stawka z
umowy ramowej") gains an effective-dated schedule so a planned MSA-rate change
takes effect only from its date. Unlike the candidate/client rates it never feeds
the margin; the schedule keeps ``contracts.framework_rate`` in sync with the step
in effect today.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from httpx import AsyncClient

from app.models.contract import Contract
from app.models.contract_framework_rate import ContractFrameworkRate


# ── Pure resolver unit tests (no DB) ─────────────────────────────────────────


def _rate(rate, on: date, to: Optional[date] = None) -> ContractFrameworkRate:
    return ContractFrameworkRate(
        rate=Decimal(str(rate)), effective_from=on, effective_to=to
    )


def test_resolver_falls_back_to_legacy_column_without_schedule():
    c = Contract()
    c.framework_rate = Decimal("215.60")
    c.framework_rate_schedule = []
    assert c.effective_framework_rate(date(2026, 6, 24)) == Decimal("215.60")


def test_resolver_picks_latest_past_step():
    c = Contract()
    c.framework_rate = Decimal("999")  # ignored once a schedule exists
    c.framework_rate_schedule = [
        _rate("200.00", date(2026, 1, 1)),
        _rate("220.50", date(2026, 6, 1)),
        _rate("240.00", date(2026, 12, 1)),
    ]
    assert c.effective_framework_rate(date(2026, 6, 24)) == Decimal("220.50")
    assert c.effective_framework_rate(date(2026, 12, 1)) == Decimal("240.00")
    assert c.effective_framework_rate(date(2026, 1, 1)) == Decimal("200.00")


def test_resolver_uses_earliest_when_all_future():
    c = Contract()
    c.framework_rate = None
    c.framework_rate_schedule = [
        _rate("200.00", date(2027, 1, 1)),
        _rate("220.00", date(2027, 6, 1)),
    ]
    # Nothing in effect yet → earliest upcoming step is the baseline.
    assert c.effective_framework_rate(date(2026, 6, 24)) == Decimal("200.00")


def test_effective_to_is_advisory_and_does_not_gate_resolution():
    c = Contract()
    c.framework_rate = None
    c.framework_rate_schedule = [
        _rate("215.60", date(2026, 1, 1), to=date(2026, 6, 30)),
    ]
    # Past the planned `effective_to`, with no later step → rate carries forward.
    assert c.effective_framework_rate(date(2026, 9, 1)) == Decimal("215.60")


# ── API integration (in-process; no-op when no seed data) ────────────────────


async def _pick_parties(app_client: AsyncClient, headers: dict):
    """Borrow candidate_id + client_id from an existing contract, if any."""
    items = (
        (await app_client.get("/api/contracts?page_size=1", headers=headers))
        .json()
        .get("items", [])
    )
    if not items:
        return None
    return items[0]["candidate_id"], items[0]["client_id"]


async def test_list_serializes_framework_schedule_field(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The contract list serializes `framework_rate_schedule` — must not trip an
    async lazy-load on the relationship."""
    resp = await app_client.get(
        "/api/contracts?page_size=5", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    for item in resp.json().get("items", []):
        assert "framework_rate_schedule" in item


async def test_create_with_framework_schedule_derives_current_rate(
    app_client: AsyncClient, app_auth_headers: dict
):
    parties = await _pick_parties(app_client, app_auth_headers)
    if parties is None:
        return
    candidate_id, client_id = parties
    today = date.today()
    past = (today - timedelta(days=30)).isoformat()
    future = (today + timedelta(days=60)).isoformat()

    payload = {
        "candidate_id": candidate_id,
        "client_id": client_id,
        "start_date": past,
        "status": "draft",
        "framework_rate_schedule": [
            {"rate": 200.50, "effective_from": past},
            {"rate": 230.00, "effective_from": future},
        ],
    }
    resp = await app_client.post(
        "/api/contracts", json=payload, headers=app_auth_headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    cid = body["id"]
    try:
        sched = body["framework_rate_schedule"]
        assert [s["rate"] for s in sched] == [200.50, 230.00]
        # Current framework rate derived = past step (future step not yet in effect).
        assert body["framework_rate"] == 200.50

        detail = (
            await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
        ).json()
        assert detail["framework_rate"] == 200.50
        assert len(detail["framework_rate_schedule"]) == 2
    finally:
        await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)


async def test_patch_replaces_framework_schedule(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The "Edycja kontraktu" form sends `framework_rate_schedule` on PATCH to
    plan a framework-rate change. The endpoint replaces the whole schedule,
    re-derives `framework_rate`, and — for an empty list — clears the schedule and
    falls back to the plain `framework_rate`."""
    parties = await _pick_parties(app_client, app_auth_headers)
    if parties is None:
        return
    candidate_id, client_id = parties
    today = date.today()
    past = (today - timedelta(days=30)).isoformat()
    mid = (today - timedelta(days=1)).isoformat()
    future = (today + timedelta(days=60)).isoformat()

    create = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": candidate_id,
            "client_id": client_id,
            "start_date": past,
            "status": "draft",
            "framework_rate": 200.00,
        },
        headers=app_auth_headers,
    )
    assert create.status_code == 201, create.text
    cid = create.json()["id"]
    try:
        patch = await app_client.patch(
            f"/api/contracts/{cid}",
            json={
                "framework_rate_schedule": [
                    {"rate": 200.00, "effective_from": past, "effective_to": mid},
                    {"rate": 230.00, "effective_from": future},
                ]
            },
            headers=app_auth_headers,
        )
        assert patch.status_code == 200, patch.text
        body = patch.json()
        sched = body["framework_rate_schedule"]
        assert [s["rate"] for s in sched] == [200.00, 230.00]
        assert sched[0]["effective_to"] == mid
        assert sched[1]["effective_to"] is None
        # Current framework rate = the step in effect today (230 is future-dated).
        assert body["framework_rate"] == 200.00

        # Empty list clears the schedule and defers to the plain framework_rate.
        patch2 = await app_client.patch(
            f"/api/contracts/{cid}",
            json={"framework_rate_schedule": [], "framework_rate": 250.00},
            headers=app_auth_headers,
        )
        assert patch2.status_code == 200, patch2.text
        body2 = patch2.json()
        assert body2["framework_rate_schedule"] == []
        assert body2["framework_rate"] == 250.00

        # Omitting the key entirely leaves the (now empty) schedule untouched.
        patch3 = await app_client.patch(
            f"/api/contracts/{cid}",
            json={"line_manager": "Jan Testowy"},
            headers=app_auth_headers,
        )
        assert patch3.status_code == 200, patch3.text
        assert patch3.json()["framework_rate"] == 250.00
    finally:
        await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)


# ── Schema acceptance ────────────────────────────────────────────────────────


def test_schemas_accept_framework_schedule():
    from app.schemas.contract import ContractCreate, ContractUpdate

    created = ContractCreate(
        candidate_id=1,
        client_id=1,
        start_date=date(2026, 7, 1),
        framework_rate_schedule=[
            {"rate": 215.60, "effective_from": date(2026, 7, 1)},
        ],
    )
    assert created.framework_rate_schedule[0].rate == 215.60

    upd = ContractUpdate(
        framework_rate_schedule=[
            {
                "rate": 230.00,
                "effective_from": date(2026, 8, 1),
                "effective_to": date(2026, 12, 31),
            }
        ]
    )
    assert upd.framework_rate_schedule[0].effective_to == date(2026, 12, 31)
