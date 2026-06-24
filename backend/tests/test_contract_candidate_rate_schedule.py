"""Tests for the effective-dated candidate-rate schedule (migracja 0144)."""

from datetime import date, timedelta

from httpx import AsyncClient

from app.models.contract import Contract
from app.models.contract_candidate_rate import ContractCandidateRate


# ── Pure resolver unit tests (no DB) ─────────────────────────────────────────


def _rate(rate: int, on: date) -> ContractCandidateRate:
    return ContractCandidateRate(rate=rate, effective_from=on)


def test_resolver_falls_back_to_legacy_column_without_schedule():
    c = Contract()
    c.rate_candidate = 100
    c.candidate_rate_schedule = []
    assert c.effective_candidate_rate(date(2026, 6, 24)) == 100


def test_resolver_picks_latest_past_step():
    c = Contract()
    c.rate_candidate = 999  # ignored once a schedule exists
    c.candidate_rate_schedule = [
        _rate(100, date(2026, 1, 1)),
        _rate(120, date(2026, 6, 1)),
        _rate(140, date(2026, 12, 1)),
    ]
    # Today between step 2 and 3 → step 2 wins.
    assert c.effective_candidate_rate(date(2026, 6, 24)) == 120
    # On/after the boundary → that step wins.
    assert c.effective_candidate_rate(date(2026, 12, 1)) == 140
    # Exactly on the first boundary.
    assert c.effective_candidate_rate(date(2026, 1, 1)) == 100


def test_resolver_uses_earliest_when_all_future():
    c = Contract()
    c.rate_candidate = None
    c.candidate_rate_schedule = [
        _rate(200, date(2027, 1, 1)),
        _rate(220, date(2027, 6, 1)),
    ]
    # Nothing in effect yet → earliest upcoming step is the baseline.
    assert c.effective_candidate_rate(date(2026, 6, 24)) == 200


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


async def test_expiring_serializes_schedule_field(
    app_client: AsyncClient, app_auth_headers: dict
):
    """/expiring returns ContractResponse incl. the schedule field — must not
    trip an async lazy-load on candidate_rate_schedule."""
    resp = await app_client.get(
        "/api/contracts/expiring", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    for item in resp.json():
        assert "candidate_rate_schedule" in item


async def test_create_with_schedule_derives_current_rate(
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
        "rate_client": 200,
        "candidate_rate_schedule": [
            {"rate": 100, "effective_from": past},
            {"rate": 130, "effective_from": future},
        ],
    }
    resp = await app_client.post(
        "/api/contracts", json=payload, headers=app_auth_headers
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    cid = body["id"]
    try:
        # Schedule persisted, ordered oldest → newest.
        sched = body["candidate_rate_schedule"]
        assert [s["rate"] for s in sched] == [100, 130]
        # Current rate derived = past step (future step not yet in effect).
        assert body["rate_candidate"] == 100
        # Margin derived from current rate.
        assert body["margin"] == 100  # 200 - 100

        # GET detail returns the same derived view.
        detail = (
            await app_client.get(
                f"/api/contracts/{cid}", headers=app_auth_headers
            )
        ).json()
        assert detail["rate_candidate"] == 100
        assert len(detail["candidate_rate_schedule"]) == 2

        # A rate_change amendment appends a future step without changing today's rate.
        amend = await app_client.post(
            f"/api/contracts/{cid}/amendments",
            json={
                "amendment_type": "rate_change",
                "effective_date": future,
                "new_rate_candidate": 150,
            },
            headers=app_auth_headers,
        )
        assert amend.status_code == 201, amend.text
        after = (
            await app_client.get(
                f"/api/contracts/{cid}", headers=app_auth_headers
            )
        ).json()
        assert len(after["candidate_rate_schedule"]) == 3
        # Still 100 today — the new step is future-dated.
        assert after["rate_candidate"] == 100
    finally:
        await app_client.delete(
            f"/api/contracts/{cid}", headers=app_auth_headers
        )
