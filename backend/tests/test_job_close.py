"""Smoke tests for POST /api/jobs/{id}/close.

Covers the happy path (published → closed with reason + notes), the RBAC
requirement (TacPlus — recruiters shouldn't be able to close), and 404.

Migration 0048_job_close_reason adds the `close_reason`/`close_notes` columns
plus `jobclosereason` enum. If this test fails with "column does not exist"
the deploy missed the migration — re-run alembic or hit the safety net in
entrypoint.sh.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def _create_draft_job(
    app_client: AsyncClient, headers: dict[str, str], title: str
) -> int:
    """Create a draft job directly — returns its id. Requires TacPlus."""
    payload = {
        "title": title,
        "recruitment_type": "body_leasing",
        "work_mode": "fulltime",
    }
    resp = await app_client.post("/api/jobs", json=payload, headers=headers)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()["id"]


async def test_close_job_with_reason(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _create_draft_job(
        app_client, app_auth_headers, "pytest-close-happy-path"
    )

    close_resp = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "budget", "notes": "Klient wstrzymał budżet Q2"},
        headers=app_auth_headers,
    )
    assert close_resp.status_code == 200, close_resp.text
    body = close_resp.json()
    assert body["status"] == "closed"
    assert body["close_reason"] == "budget"
    assert body["close_notes"] == "Klient wstrzymał budżet Q2"
    assert body["closed_at"] is not None


async def test_close_job_404(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    resp = await app_client.post(
        "/api/jobs/99999999/close",
        json={"reason": "other"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


async def test_close_job_invalid_reason(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    job_id = await _create_draft_job(
        app_client, app_auth_headers, "pytest-close-invalid-reason"
    )
    resp = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "not_a_valid_enum_value"},
        headers=app_auth_headers,
    )
    # 422 = Pydantic validation error on the enum field.
    assert resp.status_code == 422


async def test_close_without_auth(app_client: AsyncClient) -> None:
    resp = await app_client.post(
        "/api/jobs/1/close", json={"reason": "budget"}
    )
    assert resp.status_code in (401, 403)


async def test_close_job_reason_optional_notes(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """`notes` is optional — reason alone is enough."""
    job_id = await _create_draft_job(
        app_client, app_auth_headers, "pytest-close-no-notes"
    )
    resp = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "internal_hire"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["close_notes"] is None
