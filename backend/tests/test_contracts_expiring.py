"""Tests for the contract "expiring soon" surfaces.

Guards the fix where /api/contracts/expiring (and the list endpoint's
`expiring_in_days` filter) must surface contracts the daily `_promote_statuses`
cron has already flipped from `active` to `ending`. Filtering on `active` alone
silently dropped every promoted contract — so the banner read 0 while contracts
were genuinely expiring, and the banner's "Pokaż" button (which filtered the
list to the date-based window) had nothing consistent to show.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient


async def _seed_candidate_minimal() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="ContractExp",
            lastname=f"X-{uuid.uuid4().hex[:6]}",
            email=f"cexp-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_client_minimal() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cl = Client(name=f"Client-{uuid.uuid4().hex[:6]}")
        db.add(cl)
        await db.commit()
        await db.refresh(cl)
        return cl.id


async def _seed_contract(*, status: str, days_to_end: int) -> tuple[int, int, int]:
    """Seed a contract ending `days_to_end` days from today.

    Returns (contract_id, candidate_id, client_id) for cleanup.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus, ContractType

    cand_id = await _seed_candidate_minimal()
    client_id = await _seed_client_minimal()

    async with AsyncSessionLocal() as db:
        c = Contract(
            candidate_id=cand_id,
            client_id=client_id,
            status=ContractStatus(status),
            contract_type=ContractType.b2b,
            start_date=date.today() - timedelta(days=120),
            end_date=date.today() + timedelta(days=days_to_end),
            rate_client=10000,
            rate_candidate=8000,
            margin=2000,
            currency="PLN",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id, cand_id, client_id


async def _cleanup(rows: list[tuple[int, int, int]]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for contract_id, _, _ in rows:
            await db.execute(delete(Contract).where(Contract.id == contract_id))
        for _, cand_id, client_id in rows:
            await db.execute(delete(Candidate).where(Candidate.id == cand_id))
            await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


@pytest.mark.asyncio
async def test_expiring_surfaces_active_and_ending(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The regression: a cron-promoted `ending` contract within the window must
    appear alongside `active` ones in /api/contracts/expiring."""
    ending = await _seed_contract(status="ending", days_to_end=10)
    active = await _seed_contract(status="active", days_to_end=20)
    try:
        r = await app_client.get("/api/contracts/expiring", headers=app_auth_headers)
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()}
        assert ending[0] in ids, "ending-status contract must be surfaced"
        assert active[0] in ids, "active contract within 30d must still be surfaced"
    finally:
        await _cleanup([ending, active])


@pytest.mark.asyncio
async def test_expiring_excludes_ended_draft_and_beyond_window(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Only live (active/ending) contracts inside the window count — `ended` and
    `draft` are excluded by status, far-future ones by date."""
    ended = await _seed_contract(status="ended", days_to_end=5)
    draft = await _seed_contract(status="draft", days_to_end=5)
    far = await _seed_contract(status="active", days_to_end=120)
    near = await _seed_contract(status="ending", days_to_end=7)
    try:
        r = await app_client.get("/api/contracts/expiring", headers=app_auth_headers)
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()}
        assert near[0] in ids
        assert ended[0] not in ids
        assert draft[0] not in ids
        assert far[0] not in ids
    finally:
        await _cleanup([ended, draft, far, near])


@pytest.mark.asyncio
async def test_list_expiring_in_days_filter(
    app_client: AsyncClient, app_auth_headers: dict
):
    """GET /api/contracts?expiring_in_days=30 returns contracts ending within the
    window regardless of stored status, excluding those beyond it — this is the
    date-based filter the banner's "Pokaż" button drives."""
    within_active = await _seed_contract(status="active", days_to_end=15)
    within_ending = await _seed_contract(status="ending", days_to_end=3)
    beyond = await _seed_contract(status="active", days_to_end=90)
    try:
        r = await app_client.get(
            "/api/contracts?expiring_in_days=30&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert within_active[0] in ids
        assert within_ending[0] in ids
        assert beyond[0] not in ids
    finally:
        await _cleanup([within_active, within_ending, beyond])


# ── Unit: shared "ending soon" predicate (no DB) ─────────────────────────────
#
# is_ending_soon is the single source of truth the contractor stats/list now
# share with the register's date window. These pure tests lock the definition so
# the two surfaces can't drift again.

from types import SimpleNamespace  # noqa: E402

from app.models.contract import ContractStatus  # noqa: E402
from app.services.contract_service import (  # noqa: E402
    ENDING_SOON_WINDOW_DAYS,
    ending_soon_window,
    is_ending_soon,
)


def _c(status, days_to_end):
    end = None if days_to_end is None else date.today() + timedelta(days=days_to_end)
    return SimpleNamespace(status=status, end_date=end)


def test_is_ending_soon_live_within_window():
    assert is_ending_soon(_c(ContractStatus.active, 20)) is True
    assert is_ending_soon(_c(ContractStatus.ending, 5)) is True


def test_is_ending_soon_boundaries_inclusive():
    assert is_ending_soon(_c(ContractStatus.active, 0)) is True
    assert is_ending_soon(_c(ContractStatus.active, ENDING_SOON_WINDOW_DAYS)) is True
    assert is_ending_soon(_c(ContractStatus.active, ENDING_SOON_WINDOW_DAYS + 1)) is False


def test_is_ending_soon_excludes_non_live_and_edge_dates():
    # Non-live statuses never count, even inside the window.
    assert is_ending_soon(_c(ContractStatus.draft, 5)) is False
    assert is_ending_soon(_c(ContractStatus.ended, 5)) is False
    # No end date, or already past → not "ending soon".
    assert is_ending_soon(_c(ContractStatus.active, None)) is False
    assert is_ending_soon(_c(ContractStatus.ending, -1)) is False


def test_ending_soon_window_span():
    start, cutoff = ending_soon_window()
    assert (cutoff - start).days == ENDING_SOON_WINDOW_DAYS
