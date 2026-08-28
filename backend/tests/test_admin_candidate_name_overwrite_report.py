"""Admin-only, read-only audit of suspected candidate identity overwrites.

The activity log contains submitted values but no reliable before-image or edit
intent. These tests therefore pin a deliberately narrow contract: the endpoint
reports review candidates, never claims causation and never mutates/backfills.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.user import User, UserRole


REPORT = "/api/admin/candidates/suspected-name-overwrites"

pytestmark = pytest.mark.asyncio


async def _admin_id(app_client: AsyncClient) -> int:
    email = app_client.headers.get("X-Test-Admin-Email")
    assert email
    async with AsyncSessionLocal() as db:
        user_id = await db.scalar(select(User.id).where(User.email == email))
    assert user_id is not None
    return user_id


async def _seed_candidate(
    *,
    name: str,
    lastname: str,
    identity: dict | None = None,
    updated_at: datetime | None = None,
) -> int:
    suffix = uuid.uuid4().hex
    now = updated_at or datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name=name,
            lastname=lastname,
            external_source="traffit",
            external_id=f"overwrite-report-{suffix}",
            custom_fields={"_nexus_identity": identity} if identity else {},
            created_at=now - timedelta(days=1),
            updated_at=now,
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _seed_activity(
    *,
    candidate_id: int,
    user_id: int | None,
    details: dict,
    created_at: datetime,
    action: str = "updated",
    external_source: str = "manual",
) -> int:
    async with AsyncSessionLocal() as db:
        activity = Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action=action,
            details=details,
            user_id=user_id,
            external_source=external_source,
            created_at=created_at,
            updated_at=created_at,
        )
        db.add(activity)
        await db.commit()
        return activity.id


async def _report_one(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    candidate_id: int,
):
    return await app_client.get(
        REPORT,
        params={"after_candidate_id": candidate_id - 1, "scan_limit": 1},
        headers=app_auth_headers,
    )


async def test_reports_mismatch_as_suspect_without_leaking_other_activity_pii(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    now = datetime.now(timezone.utc)
    candidate_id = await _seed_candidate(
        name="Anna",
        lastname="Fabryczna Projekt X",
        updated_at=now,
        identity={
            "name_manual": False,
            "lastname_manual": False,
            "traffit_name": "Anna",
            "traffit_lastname": "Fabryczna Projekt X",
            "traffit_source_updated_at": "2026-08-28T01:00:00+00:00",
        },
    )
    admin_id = await _admin_id(app_client)
    activity_id = await _seed_activity(
        candidate_id=candidate_id,
        user_id=admin_id,
        details={
            "name": "Anna",
            "lastname": "Poprawna",
            "email": "activity-email-canary@example.com",
            "phone": "+48-activity-phone-canary",
        },
        created_at=now - timedelta(hours=1),
    )

    async with AsyncSessionLocal() as db:
        before_candidate = (
            await db.execute(
                select(
                    Candidate.name,
                    Candidate.lastname,
                    Candidate.custom_fields,
                ).where(Candidate.id == candidate_id)
            )
        ).one()
        before_activity_count = await db.scalar(
            select(func.count(Activity.id)).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
            )
        )

    response = await _report_one(app_client, app_auth_headers, candidate_id)

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert "activity-email-canary@example.com" not in response.text
    assert "+48-activity-phone-canary" not in response.text

    body = response.json()
    assert body["read_only"] is True
    assert body["verdict"] == "suspects_only_not_proof"
    assert body["count_scope"] == "current_page"
    assert body["page_matched_candidates"] == 1
    assert body["page_matched_fields"] == 1
    candidate = body["candidates"][0]
    assert candidate["candidate_id"] == candidate_id
    assert candidate["profile_path"] == f"/candidates/{candidate_id}"
    assert candidate["identity_state_present"] is True
    field = candidate["fields"][0]
    assert field == {
        "field": "lastname",
        "status": "suspect",
        "current_value": "Fabryczna Projekt X",
        "last_logged_submission_value": "Poprawna",
        "difference_kind": "material",
        "activity_id": activity_id,
        "submitted_at": (now - timedelta(hours=1)).isoformat(),
        "submitted_by_user_id": admin_id,
        "candidate_updated_after_submission": True,
        "manual_lock_active": False,
        "ownership_reason": None,
        "traffit_snapshot_value": "Fabryczna Projekt X",
        "traffit_source_updated_at": "2026-08-28T01:00:00+00:00",
        "source_alignment": "matches_current_traffit_snapshot",
        "suspect_reasons": [
            "latest_logged_submission_differs_from_current",
            "candidate_updated_after_submission",
            "current_matches_latest_traffit_snapshot",
        ],
    }

    async with AsyncSessionLocal() as db:
        after_candidate = (
            await db.execute(
                select(
                    Candidate.name,
                    Candidate.lastname,
                    Candidate.custom_fields,
                ).where(Candidate.id == candidate_id)
            )
        ).one()
        after_activity_count = await db.scalar(
            select(func.count(Activity.id)).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
            )
        )
    assert after_candidate == before_candidate
    assert after_activity_count == before_activity_count


async def test_latest_submission_is_selected_independently_for_each_field(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    now = datetime.now(timezone.utc)
    candidate_id = await _seed_candidate(
        name="Karolina Source", lastname="Nowak Source", updated_at=now
    )
    admin_id = await _admin_id(app_client)
    await _seed_activity(
        candidate_id=candidate_id,
        user_id=admin_id,
        details={"name": "Karolina Old", "lastname": "Nowak Old"},
        created_at=now - timedelta(hours=3),
    )
    latest_lastname_id = await _seed_activity(
        candidate_id=candidate_id,
        user_id=admin_id,
        details={"lastname": "Nowak Manual"},
        created_at=now - timedelta(hours=2),
    )
    latest_name_id = await _seed_activity(
        candidate_id=candidate_id,
        user_id=admin_id,
        details={"name": "Karolina Manual"},
        created_at=now - timedelta(hours=1),
    )

    response = await _report_one(app_client, app_auth_headers, candidate_id)

    assert response.status_code == 200, response.text
    fields = {
        field["field"]: field for field in response.json()["candidates"][0]["fields"]
    }
    assert fields["name"]["last_logged_submission_value"] == "Karolina Manual"
    assert fields["name"]["activity_id"] == latest_name_id
    assert fields["lastname"]["last_logged_submission_value"] == "Nowak Manual"
    assert fields["lastname"]["activity_id"] == latest_lastname_id


async def test_later_payload_equal_to_current_deliberately_masks_older_correction(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    now = datetime.now(timezone.utc)
    candidate_id = await _seed_candidate(
        name="Source Name", lastname="Source Lastname", updated_at=now
    )
    admin_id = await _admin_id(app_client)
    await _seed_activity(
        candidate_id=candidate_id,
        user_id=admin_id,
        details={"name": "Manual Name"},
        created_at=now - timedelta(hours=2),
    )
    await _seed_activity(
        candidate_id=candidate_id,
        user_id=admin_id,
        details={"name": "Source Name"},
        created_at=now - timedelta(hours=1),
    )

    response = await _report_one(app_client, app_auth_headers, candidate_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page_matched_candidates"] == 0
    assert body["candidates"] == []
    assert "latest_submission_only" in {
        limitation["code"] for limitation in body["limitations"]
    }


async def test_imported_system_and_malformed_activities_are_not_manual_evidence(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    now = datetime.now(timezone.utc)
    candidate_id = await _seed_candidate(
        name="Source Name", lastname="Source Lastname", updated_at=now
    )
    admin_id = await _admin_id(app_client)
    await _seed_activity(
        candidate_id=candidate_id,
        user_id=admin_id,
        details={"name": "Traffit Name"},
        created_at=now - timedelta(hours=4),
        external_source="traffit",
    )
    await _seed_activity(
        candidate_id=candidate_id,
        user_id=None,
        details={"lastname": "System Lastname"},
        created_at=now - timedelta(hours=3),
    )
    await _seed_activity(
        candidate_id=candidate_id,
        user_id=admin_id,
        details={"name": "Created Name"},
        created_at=now - timedelta(hours=2),
        action="created",
    )
    await _seed_activity(
        candidate_id=candidate_id,
        user_id=admin_id,
        details={"name": 12345},
        created_at=now - timedelta(hours=1),
    )

    response = await _report_one(app_client, app_auth_headers, candidate_id)

    assert response.status_code == 200, response.text
    assert response.json()["candidates"] == []


async def test_later_explicit_restore_suppresses_old_manual_submission(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    now = datetime.now(timezone.utc)
    candidate_id = await _seed_candidate(
        name="Source Name", lastname="Source Lastname", updated_at=now
    )
    admin_id = await _admin_id(app_client)
    await _seed_activity(
        candidate_id=candidate_id,
        user_id=admin_id,
        details={"name": "Manual Name"},
        created_at=now - timedelta(hours=2),
    )
    await _seed_activity(
        candidate_id=candidate_id,
        user_id=admin_id,
        details={"fields": ["name"], "owner": "traffit"},
        created_at=now - timedelta(hours=1),
        action="candidate_identity_restored_from_traffit",
        external_source="audit",
    )

    response = await _report_one(app_client, app_auth_headers, candidate_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page_matched_candidates"] == 0
    assert body["page_matched_fields"] == 0
    assert body["candidates"] == []


async def test_unresolved_bootstrap_mismatch_requires_review_without_activity(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    now = datetime.now(timezone.utc)
    candidate_id = await _seed_candidate(
        name="Anna",
        lastname="Kowalska bez projektu",
        updated_at=now,
        identity={
            "traffit_name": "Anna",
            "traffit_lastname": "Kowalska Projekt X",
            "traffit_source_updated_at": "2026-08-28T01:00:00+00:00",
            "lastname_manual": True,
            "lastname_ownership_reason": "bootstrap_mismatch",
            "lastname_set_at": "2026-08-28T01:00:01+00:00",
        },
    )

    response = await _report_one(app_client, app_auth_headers, candidate_id)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count_scope"] == "current_page"
    assert body["page_matched_candidates"] == 1
    assert body["page_matched_fields"] == 1
    candidate = body["candidates"][0]
    assert candidate["candidate_id"] == candidate_id
    assert candidate["fields"] == [
        {
            "field": "lastname",
            "status": "review_required",
            "current_value": "Kowalska bez projektu",
            "last_logged_submission_value": None,
            "difference_kind": "material",
            "activity_id": None,
            "submitted_at": None,
            "submitted_by_user_id": None,
            "candidate_updated_after_submission": False,
            "manual_lock_active": True,
            "ownership_reason": "bootstrap_mismatch",
            "traffit_snapshot_value": "Kowalska Projekt X",
            "traffit_source_updated_at": "2026-08-28T01:00:00+00:00",
            "source_alignment": "does_not_match_current_traffit_snapshot",
            "suspect_reasons": ["bootstrap_mismatch_requires_review"],
        }
    ]


async def test_report_is_admin_only(app_client: AsyncClient) -> None:
    assert (await app_client.get(REPORT)).status_code in (401, 403)

    suffix = uuid.uuid4().hex[:8]
    email = f"overwrite-report-recruiter-{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Overwrite Report Recruiter",
                role=UserRole.recruiter,
                is_active=True,
                email_verified=True,
                profile_completed=True,
            )
        )
        await db.commit()

    login = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await app_client.get(REPORT, headers=headers)).status_code == 403


async def test_candidate_id_cursor_bounds_each_page(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    now = datetime.now(timezone.utc)
    first_id = await _seed_candidate(
        name="First Source", lastname="Page", updated_at=now
    )
    second_id = await _seed_candidate(
        name="Second Source", lastname="Page", updated_at=now
    )
    assert second_id > first_id
    admin_id = await _admin_id(app_client)
    for candidate_id, manual_name in (
        (first_id, "First Manual"),
        (second_id, "Second Manual"),
    ):
        await _seed_activity(
            candidate_id=candidate_id,
            user_id=admin_id,
            details={"name": manual_name},
            created_at=now - timedelta(hours=1),
        )

    first_response = await app_client.get(
        REPORT,
        params={"after_candidate_id": first_id - 1, "scan_limit": 1},
        headers=app_auth_headers,
    )
    assert first_response.status_code == 200, first_response.text
    first = first_response.json()
    assert first["count_scope"] == "current_page"
    assert first["page_matched_candidates"] == 1
    assert first["page_matched_fields"] == 1
    assert first["scan"] == {
        "after_candidate_id": first_id - 1,
        "scan_limit": 1,
        "scanned_candidates": 1,
        "first_candidate_id": first_id,
        "last_candidate_id": first_id,
        "next_after_candidate_id": first_id,
        "done": False,
    }
    assert [row["candidate_id"] for row in first["candidates"]] == [first_id]

    second_response = await app_client.get(
        REPORT,
        params={
            "after_candidate_id": first["scan"]["next_after_candidate_id"],
            "scan_limit": 1,
        },
        headers=app_auth_headers,
    )
    assert second_response.status_code == 200, second_response.text
    second = second_response.json()
    assert second["count_scope"] == "current_page"
    assert second["page_matched_candidates"] == 1
    assert second["page_matched_fields"] == 1
    assert second["scan"]["first_candidate_id"] == second_id
    assert second["scan"]["last_candidate_id"] == second_id
    assert second["scan"]["next_after_candidate_id"] is None
    assert second["scan"]["done"] is True
    assert [row["candidate_id"] for row in second["candidates"]] == [second_id]
