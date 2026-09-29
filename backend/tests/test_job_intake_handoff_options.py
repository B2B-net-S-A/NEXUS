"""/jobs/new — czy „Przydziel automatycznie” da się wybrać przed założeniem rekrutacji."""

import pytest

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.recruitment_allocation import RecruitmentAllocationState
from app.models.user import UserRole
from tests._jarvis_helpers import make_user

URL = "/api/job-intake/handoff-options"


async def _stored_mode() -> str:
    async with AsyncSessionLocal() as db:
        state = await db.get(RecruitmentAllocationState, 1)
        return state.mode if state else "off"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_options_follow_the_allocation_flag(
    app_client, app_auth_headers, monkeypatch, enabled
) -> None:
    monkeypatch.setattr(settings, "RECRUITMENT_ALLOCATION_ENABLED", enabled)

    resp = await app_client.get(URL, headers=app_auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["automatic_enabled"] is enabled
    # Tryb czytany z tego samego wiersza co panel automatu przydziału.
    assert body["mode"] == await _stored_mode()
    assert body["mode"] in {"off", "shadow", "auto"}


@pytest.mark.asyncio
async def test_delivery_lead_reads_the_options(app_client) -> None:
    _, headers = await make_user(UserRole.delivery_lead)

    resp = await app_client.get(URL, headers=headers)

    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_recruiter_cannot_read_the_options(app_client) -> None:
    # Strona /jobs/new jest dla admina i Delivery Leada (jak /read i /read-file).
    _, headers = await make_user(UserRole.recruiter)

    resp = await app_client.get(URL, headers=headers)

    assert resp.status_code == 403, resp.text
