"""Tests for the effective-dated client-rate schedule (migracja 0151).

Mirror of ``test_contract_candidate_rate_schedule.py``. The client rate must
defer a future-dated ``rate_change`` amendment exactly like the candidate rate:
the running order keeps the OLD client rate until the amendment's
``effective_date`` (the next order), so the margin of the current period is not
silently recomputed at the new rate.
"""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.api.contracts import _effective_rate_fields
from app.models.contract import Contract, RateUnit
from app.models.contract_client_rate import ContractClientRate


# ── Pure resolver unit tests (no DB) ─────────────────────────────────────────


def _crate(rate: int, on: date) -> ContractClientRate:
    return ContractClientRate(rate=rate, effective_from=on)


def test_client_resolver_falls_back_to_legacy_column_without_schedule():
    c = Contract()
    c.rate_client = 200
    c.client_rate_schedule = []
    assert c.effective_client_rate(date(2026, 6, 24)) == 200


def test_client_resolver_picks_latest_past_step():
    c = Contract()
    c.rate_client = 999  # ignored once a schedule exists
    c.client_rate_schedule = [
        _crate(200, date(2026, 1, 1)),
        _crate(220, date(2026, 6, 1)),
        _crate(260, date(2026, 12, 1)),
    ]
    # Today between step 2 and 3 → step 2 wins.
    assert c.effective_client_rate(date(2026, 6, 24)) == 220
    # On/after the boundary → that step wins.
    assert c.effective_client_rate(date(2026, 12, 1)) == 260
    # Exactly on the first boundary.
    assert c.effective_client_rate(date(2026, 1, 1)) == 200


def test_client_resolver_uses_earliest_when_all_future():
    c = Contract()
    c.rate_client = None
    c.client_rate_schedule = [
        _crate(300, date(2027, 1, 1)),
        _crate(320, date(2027, 6, 1)),
    ]
    # Nothing in effect yet → earliest upcoming step is the baseline.
    assert c.effective_client_rate(date(2026, 6, 24)) == 300


def test_client_resolver_same_date_amendment_supersedes_baseline():
    """Mirror guard: a same-day client rate_change must beat the seeded-baseline
    tie, so the client rate/margin reflect the new order's rate."""
    c = Contract()
    c.rate_client = 200
    c.client_rate_schedule = [
        _crate(200, date(2026, 7, 1)),  # seeded baseline
        _crate(240, date(2026, 7, 1)),  # amendment, same effective_from
    ]
    assert c.effective_client_rate(date(2026, 7, 1)) == 240


def test_future_client_rate_change_keeps_old_rate_and_margin_today():
    """The bug guard: a future-dated client rate must NOT change today's
    rate/margin. Old client rate (200) holds until the new order; the new rate
    (260) applies only from its effective_date. Margin today = 200 - 100."""
    today = date(2026, 6, 24)
    future = date(2026, 9, 1)
    c = Contract()
    c.rate_unit = RateUnit.monthly
    c.rate_candidate = 100
    c.rate_client = 200
    c.candidate_rate_schedule = []
    # Simulate the amendment: baseline step (from start) + future step.
    c.client_rate_schedule = [
        _crate(200, date(2026, 1, 1)),
        _crate(260, future),
    ]
    fields_today = _effective_rate_fields(c, today)
    assert fields_today["rate_client"] == 200
    assert fields_today["margin"] == Decimal("100")  # 200 - 100, OLD rate

    # On/after the effective date the new rate (and margin) take over.
    fields_future = _effective_rate_fields(c, future)
    assert fields_future["rate_client"] == 260
    assert fields_future["margin"] == Decimal("160")  # 260 - 100


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


async def test_future_rate_change_defers_client_rate(
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
        "rate_candidate": 100,
        "rate_client": 200,
    }
    resp = await app_client.post(
        "/api/contracts", json=payload, headers=app_auth_headers
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    try:
        # A future-dated client rate_change appends a step WITHOUT changing
        # today's client rate (old rate holds to the end of the current order).
        amend = await app_client.post(
            f"/api/contracts/{cid}/amendments",
            json={
                "amendment_type": "rate_change",
                "effective_date": future,
                "new_rate_client": 260,
            },
            headers=app_auth_headers,
        )
        assert amend.status_code == 201, amend.text

        after = (
            await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
        ).json()
        # Schedule seeded baseline (200) + future step (260).
        assert [s["rate"] for s in after["client_rate_schedule"]] == [200, 260]
        # Still 200 today — the new step is future-dated.
        assert after["rate_client"] == 200
        # Margin today stays 200 - 100, NOT 260 - 100.
        assert after["margin"] == 100
    finally:
        await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
