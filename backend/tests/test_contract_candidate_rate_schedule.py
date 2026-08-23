"""Tests for the effective-dated candidate-rate schedule (migracja 0144)."""

from datetime import date, timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.api.contracts import _effective_rate_fields
from app.models.contract import Contract, RateUnit
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


def test_resolver_same_date_amendment_supersedes_baseline():
    """A same-day "Zmień stawkę" must win the tie against the seeded baseline.

    When the amendment's ``effective_date`` equals ``start_date``, the endpoint
    seeds a baseline step (old rate) and appends the new step — both share
    ``effective_from``. The later-inserted step (the amendment) must win, else
    the margin keeps using the stale rate (the reported 205−150 instead of the
    correct 205−165).
    """
    c = Contract()
    c.rate_candidate = 150
    c.candidate_rate_schedule = [
        _rate(150, date(2026, 7, 1)),  # seeded baseline ("Stawka początkowa")
        _rate(165, date(2026, 7, 1)),  # amendment, same effective_from
    ]
    assert c.effective_candidate_rate(date(2026, 7, 1)) == 165


def test_effective_to_is_advisory_and_does_not_gate_resolution():
    """`effective_to` ("Obowiązuje do") documents a planned window but must not
    change resolution — the current rate stays keyed on `effective_from`, so a
    step carries forward past its planned end until a later step supersedes it."""
    c = Contract()
    c.rate_candidate = None
    c.candidate_rate_schedule = [
        ContractCandidateRate(
            rate=120,
            effective_from=date(2026, 1, 1),
            effective_to=date(2026, 6, 30),
        )
    ]
    # Before the window — the earliest upcoming step is the baseline.
    assert c.effective_candidate_rate(date(2025, 12, 1)) == 120
    # Inside the window.
    assert c.effective_candidate_rate(date(2026, 3, 1)) == 120
    # Past the planned `effective_to`, with no later step → rate carries forward.
    assert c.effective_candidate_rate(date(2026, 9, 1)) == 120


def test_same_date_candidate_amendment_updates_margin():
    """End-to-end guard for the reported bug: client 205, candidate 150→165 on
    the same day → margin must be 205−165 = 40 (not 205−150 = 55)."""
    on = date(2026, 7, 1)
    c = Contract()
    c.rate_unit = RateUnit.hourly
    c.billing_hours_per_month = 160
    c.rate_client = 205
    c.rate_candidate = 150
    c.client_rate_schedule = []  # client rate unchanged
    c.candidate_rate_schedule = [
        _rate(150, on),
        _rate(165, on),
    ]
    fields = _effective_rate_fields(c, on)
    assert fields["rate_candidate"] == 165
    assert fields["margin"] == Decimal("40")  # 205 - 165
    assert fields["monthly_margin"] == Decimal("6400")  # 40 * 160


# ── API integration (in-process; no-op when no seed data) ────────────────────


from tests._contract_parties import pick_parties as _pick_parties

async def test_expiring_serializes_schedule_field(
    app_client: AsyncClient, app_auth_headers: dict
):
    """/expiring returns ContractResponse incl. the schedule field — must not
    trip an async lazy-load on candidate_rate_schedule."""
    resp = await app_client.get("/api/contracts/expiring", headers=app_auth_headers)
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
            await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
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
            await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
        ).json()
        assert len(after["candidate_rate_schedule"]) == 3
        # Still 100 today — the new step is future-dated.
        assert after["rate_candidate"] == 100
    finally:
        await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)


async def test_patch_replaces_schedule_with_progressive_steps(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The "Edycja kontraktu" form sends `candidate_rate_schedule` on PATCH to
    plan a progressive rate. The endpoint replaces the whole schedule (incl.
    `effective_to`), re-derives the current `rate_candidate`, and — for an empty
    list — clears the schedule and falls back to the plain `rate_candidate`."""
    parties = await _pick_parties(app_client, app_auth_headers)
    if parties is None:
        return
    candidate_id, client_id = parties
    today = date.today()
    past = (today - timedelta(days=30)).isoformat()
    mid = (today - timedelta(days=1)).isoformat()
    future = (today + timedelta(days=60)).isoformat()

    # Plain single-rate contract (no schedule yet).
    create = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": candidate_id,
            "client_id": client_id,
            "start_date": past,
            "status": "draft",
            "rate_client": 200,
            "rate_candidate": 100,
        },
        headers=app_auth_headers,
    )
    assert create.status_code == 201, create.text
    cid = create.json()["id"]
    try:
        # PATCH a progressive schedule: 100 (past→yesterday), 130 (future→…).
        patch = await app_client.patch(
            f"/api/contracts/{cid}",
            json={
                "candidate_rate_schedule": [
                    {"rate": 100, "effective_from": past, "effective_to": mid},
                    {"rate": 130, "effective_from": future},
                ]
            },
            headers=app_auth_headers,
        )
        assert patch.status_code == 200, patch.text
        body = patch.json()
        sched = body["candidate_rate_schedule"]
        assert [s["rate"] for s in sched] == [100, 130]
        # "Obowiązuje do" persisted for the first step, null for the open one.
        assert sched[0]["effective_to"] == mid
        assert sched[1]["effective_to"] is None
        # Current rate derived = the step in effect today (130 is future-dated).
        assert body["rate_candidate"] == 100
        assert body["margin"] == 100  # 200 - 100

        # Re-PATCH REPLACES the schedule wholesale (single step now).
        patch2 = await app_client.patch(
            f"/api/contracts/{cid}",
            json={
                "candidate_rate_schedule": [{"rate": 150, "effective_from": past}]
            },
            headers=app_auth_headers,
        )
        assert patch2.status_code == 200, patch2.text
        body2 = patch2.json()
        assert len(body2["candidate_rate_schedule"]) == 1
        assert body2["rate_candidate"] == 150
        assert body2["margin"] == 50  # 200 - 150

        # Empty list clears the schedule and defers to the plain rate_candidate.
        patch3 = await app_client.patch(
            f"/api/contracts/{cid}",
            json={"candidate_rate_schedule": [], "rate_candidate": 90},
            headers=app_auth_headers,
        )
        assert patch3.status_code == 200, patch3.text
        body3 = patch3.json()
        assert body3["candidate_rate_schedule"] == []
        assert body3["rate_candidate"] == 90
        assert body3["margin"] == 110  # 200 - 90

        # Omitting the key entirely leaves the (now empty) schedule untouched.
        patch4 = await app_client.patch(
            f"/api/contracts/{cid}",
            json={"line_manager": "Jan Testowy"},
            headers=app_auth_headers,
        )
        assert patch4.status_code == 200, patch4.text
        assert patch4.json()["rate_candidate"] == 90
    finally:
        await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)


# ── Fractional framework/target rates (fix „Request failed with 422") ────────
# „Stawka z umowy ramowej" 215,60 wywalała PATCH 422-ką: schematy miały
# `Optional[int]`, a Pydantic odrzuca float z częścią ułamkową (nie zaokrągla).
# Kolumny są teraz NUMERIC(12,2) (migracja 0157), schematy — float.


def test_contract_update_accepts_fractional_framework_and_target_rates():
    from app.schemas.contract import ContractUpdate

    upd = ContractUpdate(
        framework_rate=215.60, target_rate_min=180.50, target_rate_max=220.75
    )
    assert upd.framework_rate == 215.60
    assert upd.target_rate_min == 180.50
    assert upd.target_rate_max == 220.75


def test_contract_create_and_response_accept_fractional_framework_rate():
    from app.schemas.contract import ContractCreate, ContractResponse

    created = ContractCreate(
        candidate_id=1, client_id=1, start_date=date(2026, 7, 1), framework_rate=215.6
    )
    assert created.framework_rate == 215.6

    # Response path: kolumna NUMERIC czyta się jako Decimal — float schema nie
    # może jej uciąć ani odrzucić.
    resp = ContractResponse(
        id=1,
        candidate_id=1,
        client_id=1,
        job_id=None,
        end_date=None,
        rate_candidate=None,
        rate_client=None,
        framework_rate=Decimal("215.60"),
        currency="PLN",
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=160,
        margin=None,
        contract_type="b2b",
        status="active",
        documents=None,
        created_at="2026-07-10T00:00:00Z",
        updated_at="2026-07-10T00:00:00Z",
    )
    assert resp.framework_rate == 215.60
