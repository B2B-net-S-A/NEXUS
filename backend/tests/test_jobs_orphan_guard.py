"""Regression tests for QA sweep PR fix/qa-jobs-orphan-cleanup.

Verifies that:
  1. POST /api/jobs without `client_id` returns 422 (Pydantic schema rejects).
  2. GET /api/jobs never lists jobs with NULL client_id (defense-in-depth
     filter in `list_jobs`, even if the DB constraint were rolled back).

Background: 2026-05-27 QA found 21 orphan job rows on prod (NO CLIENT, POLL,
[E2E-PendingVerif] DELETE ME, etc). Migration 0120 added NOT NULL on
`jobs.client_id`. These tests guard the contract going forward.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_post_jobs_requires_client_id(
    app_client: AsyncClient, app_auth_headers: dict
):
    """JobCreate schema rejects payload without `client_id`."""
    resp = await app_client.post(
        "/api/jobs",
        json={"title": f"OrphanGuard-{uuid.uuid4().hex[:6]}"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    body = resp.json()
    # Pydantic v2 validation error structure
    assert "detail" in body
    fields = {tuple(item["loc"]) for item in body["detail"]}
    assert ("body", "client_id") in fields


@pytest.mark.asyncio
async def test_list_jobs_excludes_null_client_id(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Even if a NULL client_id job somehow exists, /api/jobs hides it.

    We can't create one via the API anymore (test above), and the DB has
    NOT NULL since migration 0120. To prove the defensive filter still
    works, we list jobs and assert *every* returned item has client_id.
    """
    resp = await app_client.get(
        "/api/jobs?page_size=100", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    for item in items:
        assert item.get("client_id") is not None, (
            f"Job {item.get('id')} leaked through list filter with "
            f"client_id=None"
        )
