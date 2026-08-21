"""Tests for Phase 9 B3 — amendments workflow."""

from datetime import date, timedelta

from httpx import AsyncClient

from app.api.contracts import _status_after_end_date_change, _synced_client_order_end
from app.models.contract import ContractStatus


# ── Pure unit tests for the client-order-end sync rule (no DB) ────────────────


def test_synced_client_order_end_follows_new_contract_end():
    """A tracked "Koniec zamówienia u klienta" moves to the new contract end."""
    assert _synced_client_order_end(date(2026, 6, 30), date(2026, 9, 30)) == date(
        2026, 9, 30
    )


def test_synced_client_order_end_stays_none_when_untracked():
    """A contract that never tracked an order end is left untracked."""
    assert _synced_client_order_end(None, date(2026, 9, 30)) is None


# ── Pure unit tests for the status↔end-date coherence rule (no DB) ────────────

_TODAY = date(2026, 7, 7)


def test_ended_with_no_end_date_resets_to_active():
    """Indefinite ("bezterminowo") contract can't read "Zakończony"."""
    assert (
        _status_after_end_date_change(ContractStatus.ended, None, _TODAY)
        == ContractStatus.active
    )


def test_ended_with_future_end_date_resets_to_active():
    """A future end date hasn't passed → not yet ended."""
    future = _TODAY + timedelta(days=30)
    assert (
        _status_after_end_date_change(ContractStatus.ended, future, _TODAY)
        == ContractStatus.active
    )


def test_ended_with_past_end_date_stays_ended():
    """Once the end date has passed, "Zakończony" is correct and preserved."""
    past = _TODAY - timedelta(days=1)
    assert (
        _status_after_end_date_change(ContractStatus.ended, past, _TODAY)
        == ContractStatus.ended
    )


def test_ended_with_end_date_today_stays_ended():
    """The end date has been reached (not in the future) → stays ended."""
    assert (
        _status_after_end_date_change(ContractStatus.ended, _TODAY, _TODAY)
        == ContractStatus.ended
    )


def test_ending_with_no_end_date_resets_to_active():
    """An indefinite contract can't be "Kończący się" either."""
    assert (
        _status_after_end_date_change(ContractStatus.ending, None, _TODAY)
        == ContractStatus.active
    )


def test_ending_with_dated_contract_is_left_to_the_cron():
    """A dated "ending" contract is the cron's domain — helper doesn't touch it."""
    soon = _TODAY + timedelta(days=10)
    assert (
        _status_after_end_date_change(ContractStatus.ending, soon, _TODAY)
        == ContractStatus.ending
    )


def test_active_and_draft_are_never_touched():
    """Downgrade only — the helper never promotes or rewrites open statuses."""
    for status in (ContractStatus.active, ContractStatus.draft):
        assert _status_after_end_date_change(status, None, _TODAY) == status
        assert (
            _status_after_end_date_change(status, _TODAY - timedelta(days=5), _TODAY)
            == status
        )


async def test_amendments_list_shape(app_client: AsyncClient, app_auth_headers: dict):
    contracts = (
        (await app_client.get("/api/contracts?page_size=1", headers=app_auth_headers))
        .json()
        .get("items", [])
    )
    if not contracts:
        return
    cid = contracts[0]["id"]
    resp = await app_client.get(
        f"/api/contracts/{cid}/amendments", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_extension_amendment_moves_end_date(
    app_client: AsyncClient, app_auth_headers: dict
):
    contracts = (
        (
            await app_client.get(
                "/api/contracts?status=active&page_size=1", headers=app_auth_headers
            )
        )
        .json()
        .get("items", [])
    )
    if not contracts:
        return
    cid = contracts[0]["id"]
    old_end = contracts[0].get("end_date")
    target = (date.today() + timedelta(days=365)).isoformat()

    payload = {
        "amendment_type": "extension",
        "effective_date": date.today().isoformat(),
        "new_end_date": target,
        "reason": "E2E test",
    }
    resp = await app_client.post(
        f"/api/contracts/{cid}/amendments",
        json=payload,
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["amendment_type"] == "extension"
    assert body["new_values"]["end_date"] == target

    # Contract's end_date is updated
    after = (
        await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
    ).json()
    assert after["end_date"] == target

    # Revert so re-running tests doesn't drift real data.
    if old_end is not None:
        revert = await app_client.post(
            f"/api/contracts/{cid}/amendments",
            json={
                "amendment_type": "extension",
                "effective_date": date.today().isoformat(),
                "new_end_date": old_end,
                "reason": "revert E2E",
            },
            headers=app_auth_headers,
        )
        assert revert.status_code == 201


async def test_rate_change_requires_at_least_one_field(
    app_client: AsyncClient, app_auth_headers: dict
):
    contracts = (
        (await app_client.get("/api/contracts?page_size=1", headers=app_auth_headers))
        .json()
        .get("items", [])
    )
    if not contracts:
        return
    cid = contracts[0]["id"]
    resp = await app_client.post(
        f"/api/contracts/{cid}/amendments",
        json={
            "amendment_type": "rate_change",
            "effective_date": date.today().isoformat(),
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


# ── Extension ⇒ client-order-end sync (in-process; no-op without seed data) ───


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


async def test_extension_syncs_client_order_end_date(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Extending a contract drags "Koniec zamówienia u klienta" to the new end
    date — it used to linger on the old order end (the reported bug)."""
    parties = await _pick_parties(app_client, app_auth_headers)
    if parties is None:
        return
    candidate_id, client_id = parties
    start = date.today().isoformat()
    old_end = (date.today() + timedelta(days=90)).isoformat()
    new_end = (date.today() + timedelta(days=180)).isoformat()

    resp = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": candidate_id,
            "client_id": client_id,
            "start_date": start,
            "end_date": old_end,
            "client_order_end_date": old_end,
            "status": "active",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    try:
        amend = await app_client.post(
            f"/api/contracts/{cid}/amendments",
            json={
                "amendment_type": "extension",
                "effective_date": date.today().isoformat(),
                "new_end_date": new_end,
            },
            headers=app_auth_headers,
        )
        assert amend.status_code == 201, amend.text
        # Audit trail records the order-end move.
        assert amend.json()["new_values"]["client_order_end_date"] == new_end

        after = (
            await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
        ).json()
        assert after["end_date"] == new_end
        assert after["client_order_end_date"] == new_end
    finally:
        await app_client.patch(
            f"/api/contracts/{cid}",
            json={"status": "draft"},
            headers=app_auth_headers,
        )
        await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)


async def test_extension_leaves_untracked_order_end_null(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A contract with no client_order_end_date must not gain one on extension."""
    parties = await _pick_parties(app_client, app_auth_headers)
    if parties is None:
        return
    candidate_id, client_id = parties
    start = date.today().isoformat()
    old_end = (date.today() + timedelta(days=90)).isoformat()
    new_end = (date.today() + timedelta(days=180)).isoformat()

    resp = await app_client.post(
        "/api/contracts",
        json={
            "candidate_id": candidate_id,
            "client_id": client_id,
            "start_date": start,
            "end_date": old_end,
            "status": "active",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]
    try:
        amend = await app_client.post(
            f"/api/contracts/{cid}/amendments",
            json={
                "amendment_type": "extension",
                "effective_date": date.today().isoformat(),
                "new_end_date": new_end,
            },
            headers=app_auth_headers,
        )
        assert amend.status_code == 201, amend.text
        assert "client_order_end_date" not in amend.json()["new_values"]

        after = (
            await app_client.get(f"/api/contracts/{cid}", headers=app_auth_headers)
        ).json()
        assert after["client_order_end_date"] is None
    finally:
        await app_client.patch(
            f"/api/contracts/{cid}",
            json={"status": "draft"},
            headers=app_auth_headers,
        )
        await app_client.delete(f"/api/contracts/{cid}", headers=app_auth_headers)
