"""Integration tests for POST /api/microsoft365/emails/bulk (Phase 5.1).

In-process httpx.ASGITransport against the postgres service in CI. Seeds Email
rows directly via AsyncSessionLocal so we don't need a working Graph mailbox.

Coverage:
- happy path for each of the 5 actions (archive / mark_read / mark_unread /
  link_to_candidate / unlink)
- RBAC: emails owned by another user surface as 'forbidden' skips, never
  silently mutated
- validation: link_to_candidate without candidate_id → 422
- request cap: >200 email_ids → 422
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate, CandidateStatus
from app.models.m365 import Email, EmailDirection, EmailMatchMethod
from app.models.user import User, UserRole


async def _create_user(email: str, role: UserRole = UserRole.recruiter) -> User:
    """Insert a User with a deterministic password and return the persisted row."""
    async with AsyncSessionLocal() as db:
        password = f"T3st_{uuid.uuid4().hex[:8]}!PassX"
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Bulk Test",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        # Carry the plaintext on the in-memory object so tests can log in.
        user._plain_password = password  # type: ignore[attr-defined]
        return user


async def _seed_email(
    user_id: int,
    *,
    candidate_id: int | None = None,
    is_read: bool = False,
    is_archived: bool = False,
) -> Email:
    """Insert a minimal Email row owned by user_id."""
    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:12]
        row = Email(
            user_id=user_id,
            candidate_id=candidate_id,
            m365_message_id=f"msg-{suffix}",
            m365_conversation_id=f"conv-{suffix}",
            from_address=f"sender-{suffix}@example.com",
            received_at=datetime.now(timezone.utc),
            direction=EmailDirection.received,
            has_attachments=False,
            is_read=is_read,
            is_archived=is_archived,
            is_private_filtered=False,
            match_method=EmailMatchMethod.unmatched,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def _seed_candidate() -> Candidate:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Bulk",
            lastname=f"Candidate-{uuid.uuid4().hex[:6]}",
            email=f"bulk-{uuid.uuid4().hex[:6]}@example.com",
            status=CandidateStatus.active,
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)
        return candidate


async def _fetch_email(email_id: int) -> Email | None:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Email).where(Email.id == email_id))


@pytest_asyncio.fixture
async def admin_user_id(app_auth_headers: dict, app_client: AsyncClient) -> int:
    """Return the seeded admin's row id (their token is in app_auth_headers)."""
    r = await app_client.get("/api/auth/me", headers=app_auth_headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── Happy paths ──────────────────────────────────────────────────────────────


async def test_bulk_archive_happy(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    e1 = await _seed_email(admin_user_id)
    e2 = await _seed_email(admin_user_id)

    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={"email_ids": [e1.id, e2.id], "action": "archive"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "archive"
    assert body["updated_count"] == 2
    assert body["skipped_count"] == 0

    after1 = await _fetch_email(e1.id)
    after2 = await _fetch_email(e2.id)
    assert after1 is not None and after1.is_archived is True
    assert after2 is not None and after2.is_archived is True


async def test_bulk_mark_read_happy(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    e1 = await _seed_email(admin_user_id, is_read=False)
    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={"email_ids": [e1.id], "action": "mark_read"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated_count"] == 1

    after = await _fetch_email(e1.id)
    assert after is not None and after.is_read is True


async def test_bulk_mark_unread_happy(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    e1 = await _seed_email(admin_user_id, is_read=True)
    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={"email_ids": [e1.id], "action": "mark_unread"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    after = await _fetch_email(e1.id)
    assert after is not None and after.is_read is False


async def test_bulk_link_to_candidate_happy(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    candidate = await _seed_candidate()
    e1 = await _seed_email(admin_user_id)

    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={
            "email_ids": [e1.id],
            "action": "link_to_candidate",
            "candidate_id": candidate.id,
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated_count"] == 1

    after = await _fetch_email(e1.id)
    assert after is not None
    assert after.candidate_id == candidate.id
    assert after.match_method == EmailMatchMethod.manual
    assert after.match_confidence == 1.0
    assert after.matched_at is not None
    assert after.matched_by_user_id == admin_user_id


async def test_bulk_unlink_happy(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    candidate = await _seed_candidate()
    e1 = await _seed_email(admin_user_id, candidate_id=candidate.id)

    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={"email_ids": [e1.id], "action": "unlink"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["updated_count"] == 1

    after = await _fetch_email(e1.id)
    assert after is not None
    assert after.candidate_id is None
    assert after.match_method == EmailMatchMethod.unmatched
    assert after.match_confidence is None
    assert after.matched_at is None
    assert after.matched_by_user_id is None


# ── RBAC ─────────────────────────────────────────────────────────────────────


async def test_bulk_rbac_other_user_email_skipped_not_mutated(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    """User A's request to archive user B's email must NOT mutate user B's row."""
    other_email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    other = await _create_user(other_email)

    own_email = await _seed_email(admin_user_id)
    foreign_email = await _seed_email(other.id)

    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={"email_ids": [own_email.id, foreign_email.id], "action": "archive"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_count"] == 1
    assert body["skipped_count"] == 1
    reasons = {err["id"]: err["reason"] for err in body["errors"]}
    assert reasons[foreign_email.id] == "forbidden"

    # Foreign row stays untouched.
    after_foreign = await _fetch_email(foreign_email.id)
    assert after_foreign is not None and after_foreign.is_archived is False
    # Own row was archived.
    after_own = await _fetch_email(own_email.id)
    assert after_own is not None and after_own.is_archived is True


async def test_bulk_not_found_id_reported(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    e1 = await _seed_email(admin_user_id)
    # Use a guaranteed-not-existing id.
    ghost_id = e1.id + 10_000_000

    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={"email_ids": [e1.id, ghost_id], "action": "mark_read"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["updated_count"] == 1
    assert body["skipped_count"] == 1
    reasons = {err["id"]: err["reason"] for err in body["errors"]}
    assert reasons[ghost_id] == "not_found"


# ── Validation ───────────────────────────────────────────────────────────────


async def test_bulk_link_to_candidate_without_candidate_id_422(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    e1 = await _seed_email(admin_user_id)
    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={"email_ids": [e1.id], "action": "link_to_candidate"},
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text


async def test_bulk_link_to_candidate_with_missing_candidate_404(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    e1 = await _seed_email(admin_user_id)
    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={
            "email_ids": [e1.id],
            "action": "link_to_candidate",
            "candidate_id": 9_999_999,
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 404, r.text


async def test_bulk_over_200_ids_422(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    too_many = list(range(1, 202))  # 201 ids
    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={"email_ids": too_many, "action": "archive"},
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text


async def test_bulk_empty_ids_422(app_client: AsyncClient, app_auth_headers: dict):
    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={"email_ids": [], "action": "archive"},
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text


async def test_bulk_unknown_action_422(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    e1 = await _seed_email(admin_user_id)
    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={"email_ids": [e1.id], "action": "delete"},
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text


async def test_bulk_archive_hides_email_from_default_thread_view(
    app_client: AsyncClient, app_auth_headers: dict, admin_user_id: int
):
    """End-to-end check used by the smoke test: archive removes from default view."""
    candidate = await _seed_candidate()
    e1 = await _seed_email(admin_user_id, candidate_id=candidate.id)

    # Visible before archive.
    r = await app_client.get(
        f"/api/candidates/{candidate.id}/emails", headers=app_auth_headers
    )
    assert r.status_code == 200, r.text
    threads = r.json()
    ids_before = {t["latest"]["id"] for t in threads}
    assert e1.id in ids_before

    # Archive.
    r = await app_client.post(
        "/api/microsoft365/emails/bulk",
        json={"email_ids": [e1.id], "action": "archive"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text

    # Hidden from default view.
    r = await app_client.get(
        f"/api/candidates/{candidate.id}/emails", headers=app_auth_headers
    )
    assert r.status_code == 200
    threads_after = r.json()
    ids_after = {t["latest"]["id"] for t in threads_after}
    assert e1.id not in ids_after

    # Still visible with include_archived=true.
    r = await app_client.get(
        f"/api/candidates/{candidate.id}/emails?include_archived=true",
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    threads_with_archived = r.json()
    ids_with_archived = {t["latest"]["id"] for t in threads_with_archived}
    assert e1.id in ids_with_archived
