"""Tests for the contractor module — validator, activate endpoint, list + stats.

Mirrors the layout of test_contracts_expansion.py: in-process `app_client`
fixture, works against whatever contracts already exist in the test DB.
The activate happy-path test is self-contained — it creates its own
candidate + client + job + draft contract so it can exercise the flow
without relying on pre-seeded data.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.models.contract import Contract, ContractType, ContractWorkMode
from app.models.contract_candidate_rate import ContractCandidateRate
from app.services.contract_service import (
    ACTIVATION_REQUIRED_FIELDS,
    ENDING_SOON_WINDOW_DAYS,
    validate_ready_for_activation,
)


# ── Unit: validator ─────────────────────────────────────────────────────────


def _fake_contract(**fields):
    """Build an object with just the attributes the validator reads.

    Using SimpleNamespace to avoid touching SQLAlchemy — the helper only
    reads via getattr so a plain bag of attributes is enough.
    """
    defaults = {name: None for name in ACTIVATION_REQUIRED_FIELDS}
    defaults.update(fields)
    return SimpleNamespace(**defaults)


def test_validate_missing_all_fields_returns_full_list():
    contract = _fake_contract()
    missing = validate_ready_for_activation(contract)
    assert missing == list(ACTIVATION_REQUIRED_FIELDS)


def test_validate_all_populated_returns_empty():
    contract = _fake_contract(
        start_date=date.today(),
        end_date=date.today() + timedelta(days=90),
        rate_candidate=15000,
        rate_client=20000,
        contract_type="b2b",
        work_mode="remote",
    )
    assert validate_ready_for_activation(contract) == []


def test_validate_partial_returns_only_missing():
    contract = _fake_contract(
        start_date=date.today(),
        rate_candidate=15000,
        contract_type="b2b",
    )
    missing = validate_ready_for_activation(contract)
    assert set(missing) == {"rate_client", "work_mode"}
    # Preserves canonical order — the UI depends on it for a stable checklist
    assert missing == [f for f in ACTIVATION_REQUIRED_FIELDS if f in missing]


def test_open_ended_contract_is_ready_to_activate():
    """Umowa BEZTERMINOWA jest kompletna — brak `end_date` to nie brak danych.

    Ta asercja jest odwrotnością poprzedniego kontraktu i to jest zamierzone:
    `end_date` w bramce dawało stan bez wyjścia (rejestr renderuje
    „bezterminowo", `_status_after_end_date_change` leczy z niej `ended` na
    `active`, a aktywować się nie dało żadną ścieżką — 409 przy każdym zapisie
    na „Aktywny").
    """
    contract = _fake_contract(
        start_date=date.today(),
        end_date=None,
        rate_candidate=15000,
        rate_client=20000,
        contract_type="b2b",
        work_mode="remote",
    )
    assert validate_ready_for_activation(contract) == []
    assert "end_date" not in ACTIVATION_REQUIRED_FIELDS


# ── Unit: bramka czyta HARMONOGRAM, nie tylko kolumnę cache'u ───────────────


def test_rate_only_in_the_schedule_satisfies_the_gate():
    """Stawka istniejąca WYŁĄCZNIE w harmonogramie przechodzi bramkę.

    ``rate_candidate`` to kolumna CACHE'UJĄCA krok obowiązujący dziś; prawdziwą
    stawką jest harmonogram. Wszystkie trzy ścieżki zapisu (POST, PATCH, aneks)
    dziś tę kolumnę dopisują, więc to zabezpieczenie, nie ścieżka główna — ale
    bez niego kontrakt ze stawką progresywną i pustą kolumną (import, legacy,
    przyszła ścieżka zapisu, która zapomni o lustrze) byłby nieaktywowalny
    z komunikatem „brakuje stawki", stojąc obok wypełnionego harmonogramu.
    """
    contract = Contract(
        start_date=date.today(),
        rate_candidate=None,
        rate_client=20000,
        contract_type=ContractType.b2b,
        work_mode=ContractWorkMode.remote,
    )
    contract.candidate_rate_schedule = [
        ContractCandidateRate(rate=15000, effective_from=date.today())
    ]
    assert validate_ready_for_activation(contract) == []


def test_future_only_schedule_also_satisfies_the_gate():
    """Harmonogram z samymi PRZYSZŁYMI krokami też jest stawką — celowo.

    Bramka nie ma własnej definicji „stawki": deleguje do
    ``effective_candidate_rate``, a ten przy samych przyszłych krokach zwraca
    NAJBLIŻSZY nadchodzący („so a fresh contract still has a rate" —
    ``_resolve_scheduled_rate``). Utrzymanie tej semantyki jest ważniejsze niż
    intuicja „na dziś nie ma stawki": druga definicja w bramce znaczyłaby, że
    kontrakt przechodzi walidację, a widoki liczą co innego — albo odwrotnie.

    Ten test istnieje, bo napisałem go najpierw z odwrotną asercją i to KOD
    miał rację. Zostaje jako zapis tej decyzji.
    """
    contract = Contract(
        start_date=date.today(),
        rate_candidate=None,
        rate_client=20000,
        contract_type=ContractType.b2b,
        work_mode=ContractWorkMode.remote,
    )
    contract.candidate_rate_schedule = [
        ContractCandidateRate(
            rate=15000, effective_from=date.today() + timedelta(days=30)
        )
    ]
    assert validate_ready_for_activation(contract) == []
    assert contract.effective_candidate_rate(date.today()) == 15000


def test_empty_schedule_falls_back_to_the_column():
    """Pusty harmonogram → decyduje kolumna; brak obu → brak stawki."""
    contract = Contract(
        start_date=date.today(),
        rate_candidate=None,
        rate_client=20000,
        contract_type=ContractType.b2b,
        work_mode=ContractWorkMode.remote,
    )
    contract.candidate_rate_schedule = []
    assert validate_ready_for_activation(contract) == ["rate_candidate"]


def test_plain_attribute_bag_does_not_explode_on_inspect():
    """Bramka bywa wołana na obiekcie NIE-ORM — ``inspect`` rzuciłby wtedy.

    Stąd ``raiseerr=False``: brak stanu ORM znaczy „nie ma jak sprawdzić
    harmonogramu", a nie „wywal request".
    """
    bag = _fake_contract(start_date=date.today(), contract_type="b2b")
    assert validate_ready_for_activation(bag) == [
        "rate_candidate",
        "rate_client",
        "work_mode",
    ]


# ── Integration: list + stats ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_contractors_returns_envelope(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get("/api/contractors", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"items", "total", "page", "page_size"}
    assert isinstance(body["items"], list)
    for item in body["items"]:
        # Every row has the fields the UI renders
        assert "contract_id" in item
        assert "candidate" in item and "id" in item["candidate"]
        assert "status" in item
        assert item["status"] in (
            "draft",
            "ready_for_signature",
            "active",
            "ending",
        )
        # missing_fields is always present (empty list for non-drafts)
        assert isinstance(item.get("missing_fields"), list)


@pytest.mark.asyncio
async def test_list_contractors_filter_by_status(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contractors?status=active", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    today = date.today()
    cutoff = today + timedelta(days=ENDING_SOON_WINDOW_DAYS)
    for item in resp.json()["items"]:
        # ``active`` is a date bucket, not an equality filter on the stored
        # status. A legacy ``ending`` row outside the 30-day window belongs in
        # this tab until the lifecycle cron normalizes its stored status.
        assert item["status"] in ("active", "ending")
        if item["end_date"] is not None:
            end_date = date.fromisoformat(item["end_date"])
            assert end_date < today or end_date > cutoff


@pytest.mark.asyncio
async def test_contractor_stats_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get("/api/contractors/stats", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"draft", "drafts_incomplete", "active", "ending"}
    # drafts_incomplete is a subset of draft
    assert body["drafts_incomplete"] <= body["draft"]
    # All non-negative
    for v in body.values():
        assert v >= 0


# ── Integration: activate endpoint ──────────────────────────────────────────


async def _find_or_create_draft(app_client: AsyncClient, headers: dict) -> dict | None:
    """Return a draft contract dict — find first, else create one.

    Creating a draft requires a candidate + client + job. Keep the setup
    defensive: if the fixtures to create those aren't available on this
    test DB, return None so the caller can skip.
    """
    existing = await app_client.get(
        "/api/contractors?status=draft&page_size=1", headers=headers
    )
    if existing.status_code == 200 and existing.json()["items"]:
        item = existing.json()["items"][0]
        detail = await app_client.get(
            f"/api/contracts/{item['contract_id']}", headers=headers
        )
        if detail.status_code == 200:
            return detail.json()
    return None


@pytest.mark.asyncio
async def test_activate_draft_returns_409_when_fields_missing(
    app_client: AsyncClient, app_auth_headers: dict
):
    draft = await _find_or_create_draft(app_client, app_auth_headers)
    if not draft:
        pytest.skip("No draft contract available in test DB")
    # Strip any prefilled fields to force a missing-fields scenario
    reset = await app_client.patch(
        f"/api/contracts/{draft['id']}",
        json={"rate_client": None, "end_date": None, "work_mode": None},
        headers=app_auth_headers,
    )
    assert reset.status_code == 200

    resp = await app_client.post(
        f"/api/contracts/{draft['id']}/activate",
        json={},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert "missing" in detail
    assert isinstance(detail["missing"], list)
    assert "rate_client" in detail["missing"]


@pytest.mark.asyncio
async def test_activate_draft_happy_path(
    app_client: AsyncClient, app_auth_headers: dict
):
    draft = await _find_or_create_draft(app_client, app_auth_headers)
    if not draft:
        pytest.skip("No draft contract available in test DB")

    # Fill every required field so activation succeeds
    fill = await app_client.patch(
        f"/api/contracts/{draft['id']}",
        json={
            "start_date": date.today().isoformat(),
            "end_date": (date.today() + timedelta(days=90)).isoformat(),
            "rate_candidate": 15000,
            "rate_client": 20000,
            "contract_type": "b2b",
            "work_mode": "remote",
        },
        headers=app_auth_headers,
    )
    assert fill.status_code == 200, fill.text

    activate = await app_client.post(
        f"/api/contracts/{draft['id']}/activate",
        json={},
        headers=app_auth_headers,
    )
    assert activate.status_code == 200, activate.text
    body = activate.json()
    assert body["status"] == "active"
    # Margin was recomputed by the model-level before_update listener
    assert body["margin"] == 5000

    # Revert so subsequent runs stay idempotent — via the audited /reopen
    # transition (free `PATCH {status: draft}` writes are no longer accepted;
    # P1-CONTRACT-01).
    revert = await app_client.post(
        f"/api/contracts/{draft['id']}/reopen",
        json={"reason": "test idempotency"},
        headers=app_auth_headers,
    )
    assert revert.status_code == 200
    assert revert.json()["status"] == "draft"


@pytest.mark.asyncio
async def test_activate_409_on_non_draft_status(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contractors?status=active&page_size=1", headers=app_auth_headers
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    if not items:
        pytest.skip("No active contract to test against")
    cid = items[0]["contract_id"]
    activate = await app_client.post(
        f"/api/contracts/{cid}/activate",
        json={},
        headers=app_auth_headers,
    )
    assert activate.status_code == 409, activate.text
    assert "already" in str(activate.json()["detail"]).lower()
