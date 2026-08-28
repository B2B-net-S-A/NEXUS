"""Manual candidate identity ownership across the Traffit sync boundary."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models.candidate import Candidate
from app.services.candidate_identity_ownership import (
    identity_sync_state,
    lock_changed_traffit_identity_fields,
    restore_traffit_identity_fields,
)


@pytest_asyncio.fixture
async def db():
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        yield session


async def _seed_editor_and_candidate(db) -> tuple[Any, Candidate]:
    from app.models.user import User, UserRole

    suffix = uuid.uuid4().hex[:10]
    editor = User(
        email=f"identity-editor-{suffix}@example.com",
        password_hash="test-only",
        name="Identity editor",
        role=UserRole.recruiter,
        is_active=True,
    )
    candidate = Candidate(
        name="Anna",
        lastname="Kowalska",
        external_source="traffit",
        external_id=f"identity-api-{suffix}",
        custom_fields={
            "_nexus_identity": {
                "traffit_name": "Anna",
                "traffit_lastname": "Kowalska",
            }
        },
    )
    db.add_all([editor, candidate])
    await db.commit()
    return editor, candidate


def _traffit_candidate() -> Candidate:
    return Candidate(
        name="Anna",
        lastname="Kowalska",
        external_source="traffit",
        external_id="123",
        custom_fields={
            "tenant_field": "preserved",
            "_nexus_identity": {
                "traffit_name": "Anna",
                "traffit_lastname": "Kowalska",
            },
        },
    )


def test_patch_locks_only_identity_field_whose_value_changed() -> None:
    candidate = _traffit_candidate()
    changed_at = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

    locked = lock_changed_traffit_identity_fields(
        candidate,
        {"name": "Anna", "lastname": "Nowak", "phone": "123"},
        user_id=17,
        changed_at=changed_at,
    )

    assert locked == ["lastname"]
    metadata = candidate.custom_fields["_nexus_identity"]
    assert "name_manual" not in metadata
    assert metadata["lastname_manual"] is True
    assert metadata["lastname_set_by"] == 17
    assert metadata["lastname_set_at"] == changed_at.isoformat()
    assert metadata["lastname_ownership_reason"] == "manual_edit"
    assert candidate.custom_fields["tenant_field"] == "preserved"
    assert (
        identity_sync_state(candidate)["lastname"]["override_token"]
        == changed_at.isoformat()
    )


def test_unrelated_patch_does_not_take_identity_ownership() -> None:
    candidate = _traffit_candidate()

    locked = lock_changed_traffit_identity_fields(
        candidate,
        {"name": "Anna", "lastname": "Kowalska", "phone": "123"},
        user_id=17,
    )

    assert locked == []
    assert identity_sync_state(candidate)["name"]["owner"] == "traffit"
    assert identity_sync_state(candidate)["lastname"]["owner"] == "traffit"


def test_restore_is_field_scoped_and_releases_only_selected_lock() -> None:
    candidate = _traffit_candidate()
    metadata = candidate.custom_fields["_nexus_identity"]
    metadata.update(
        {
            "name_manual": True,
            "lastname_manual": True,
            "name_set_at": "2026-08-28T12:00:00+00:00",
            "lastname_set_at": "2026-08-28T12:00:00+00:00",
        }
    )
    candidate.name = "Ania"
    candidate.lastname = "Nowak"

    restored = restore_traffit_identity_fields(
        candidate,
        ["lastname"],
        expected_current_values={"lastname": "Nowak"},
        expected_source_values={"lastname": "Kowalska"},
        expected_override_tokens={"lastname": "2026-08-28T12:00:00+00:00"},
    )

    assert restored == ["lastname"]
    assert candidate.name == "Ania"
    assert candidate.lastname == "Kowalska"
    state = identity_sync_state(candidate)
    assert state["name"]["owner"] == "nexus"
    assert state["lastname"]["owner"] == "traffit"


def test_restore_rejects_source_value_changed_after_confirmation() -> None:
    candidate = _traffit_candidate()
    candidate.lastname = "Nowak"
    candidate.custom_fields["_nexus_identity"]["lastname_manual"] = True
    candidate.custom_fields["_nexus_identity"]["traffit_lastname"] = "Wiśniewska"
    candidate.custom_fields["_nexus_identity"]["lastname_set_at"] = (
        "2026-08-28T12:00:00+00:00"
    )

    with pytest.raises(ValueError, match="traffit_identity_value_changed:lastname"):
        restore_traffit_identity_fields(
            candidate,
            ["lastname"],
            expected_current_values={"lastname": "Nowak"},
            expected_source_values={"lastname": "Kowalska"},
            expected_override_tokens={"lastname": "2026-08-28T12:00:00+00:00"},
        )

    assert candidate.lastname == "Nowak"
    assert identity_sync_state(candidate)["lastname"]["owner"] == "nexus"


def test_restore_rejects_newer_manual_value_after_confirmation() -> None:
    candidate = _traffit_candidate()
    candidate.lastname = "Nowsza korekta"
    candidate.custom_fields["_nexus_identity"]["lastname_manual"] = True
    candidate.custom_fields["_nexus_identity"]["lastname_set_at"] = (
        "2026-08-28T12:00:00+00:00"
    )

    with pytest.raises(ValueError, match="nexus_identity_value_changed:lastname"):
        restore_traffit_identity_fields(
            candidate,
            ["lastname"],
            expected_current_values={"lastname": "Starsza korekta"},
            expected_source_values={"lastname": "Kowalska"},
            expected_override_tokens={"lastname": "2026-08-28T12:00:00+00:00"},
        )

    assert candidate.lastname == "Nowsza korekta"


def test_restore_rejects_a_new_lock_even_when_values_are_identical() -> None:
    candidate = _traffit_candidate()
    candidate.lastname = "Nowak"
    metadata = candidate.custom_fields["_nexus_identity"]
    metadata["lastname_manual"] = True
    metadata["lastname_set_at"] = "2026-08-28T12:05:00+00:00"

    with pytest.raises(ValueError, match="identity_override_version_changed:lastname"):
        restore_traffit_identity_fields(
            candidate,
            ["lastname"],
            expected_current_values={"lastname": "Nowak"},
            expected_source_values={"lastname": "Kowalska"},
            expected_override_tokens={"lastname": "2026-08-28T12:00:00+00:00"},
        )

    assert candidate.lastname == "Nowak"
    assert metadata["lastname_manual"] is True


def test_local_candidate_has_no_traffit_identity_projection_or_lock() -> None:
    candidate = Candidate(name="Jan", lastname="Nowak", external_source=None)

    assert identity_sync_state(candidate) is None
    assert (
        lock_changed_traffit_identity_fields(
            candidate,
            {"lastname": "Kowalski"},
            user_id=17,
        )
        == []
    )


def test_both_importer_write_paths_preserve_locks_and_refresh_snapshot() -> None:
    from app.services.traffit.importer import (
        _UPDATE_CANDIDATE_ADOPT,
        _UPSERT_CANDIDATE,
    )

    for statement in (_UPSERT_CANDIDATE, _UPDATE_CANDIDATE_ADOPT):
        sql = str(statement)
        assert "{_nexus_identity,name_manual}" in sql
        assert "{_nexus_identity,lastname_manual}" in sql
        assert "traffit_name" in sql
        assert "traffit_lastname" in sql
        assert "traffit_source_updated_at" in sql
        assert "traffit_raw_name" in sql
        assert "traffit_raw_lastname" in sql


@pytest.mark.asyncio
async def test_patch_and_restore_round_trip_is_audited_without_new_pii(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.index_outbox_service as outbox
    from app.api.candidates import (
        restore_candidate_identity_from_traffit,
        update_candidate,
    )
    from app.models.activity import Activity
    from app.schemas.candidate import (
        CandidateIdentityRestoreRequest,
        CandidateUpdate,
    )

    embed = AsyncMock(return_value=True)
    monkeypatch.setattr(outbox, "schedule_or_embed_candidate", embed)
    editor, candidate = await _seed_editor_and_candidate(db)

    updated = await update_candidate(
        candidate.id,
        CandidateUpdate(name="Anna", lastname="Nowak"),
        current_user=SimpleNamespace(id=editor.id),
        db=db,
    )
    assert updated.lastname == "Nowak"
    assert updated.identity_sync.name.owner == "traffit"
    assert updated.identity_sync.lastname.owner == "nexus"
    override_token = updated.identity_sync.lastname.override_token
    assert override_token is not None

    restored = await restore_candidate_identity_from_traffit(
        candidate.id,
        CandidateIdentityRestoreRequest(
            fields=["lastname"],
            expected_current_values={"lastname": "Nowak"},
            expected_traffit_values={"lastname": "Kowalska"},
            expected_override_tokens={"lastname": override_token},
        ),
        current_user=SimpleNamespace(id=editor.id),
        db=db,
    )
    assert restored.lastname == "Kowalska"
    assert restored.identity_sync.lastname.owner == "traffit"

    audit_result = await db.execute(
        select(Activity)
        .where(
            Activity.entity_id == candidate.id,
            Activity.action.in_(
                [
                    "candidate_identity_manual_ownership_set",
                    "candidate_identity_restored_from_traffit",
                ]
            ),
        )
        .order_by(Activity.id)
    )
    audit = audit_result.scalars().all()
    assert [event.details for event in audit] == [
        {"fields": ["lastname"], "owner": "nexus"},
        {"fields": ["lastname"], "owner": "traffit"},
    ]
    embed.assert_awaited()


@pytest.mark.asyncio
async def test_restore_api_rejects_a_newer_manual_edit(
    db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.index_outbox_service as outbox
    from fastapi import HTTPException

    from app.api.candidates import restore_candidate_identity_from_traffit
    from app.schemas.candidate import CandidateIdentityRestoreRequest

    embed = AsyncMock(return_value=True)
    monkeypatch.setattr(outbox, "schedule_or_embed_candidate", embed)
    editor, candidate = await _seed_editor_and_candidate(db)
    candidate.lastname = "Nowsza korekta"
    candidate.custom_fields = {
        "_nexus_identity": {
            "lastname_manual": True,
            "lastname_set_at": "2026-08-28T12:00:00+00:00",
            "traffit_name": "Anna",
            "traffit_lastname": "Kowalska",
        }
    }
    await db.commit()

    with pytest.raises(HTTPException) as caught:
        await restore_candidate_identity_from_traffit(
            candidate.id,
            CandidateIdentityRestoreRequest(
                fields=["lastname"],
                expected_current_values={"lastname": "Starsza korekta"},
                expected_traffit_values={"lastname": "Kowalska"},
                expected_override_tokens={"lastname": "2026-08-28T12:00:00+00:00"},
            ),
            current_user=SimpleNamespace(id=editor.id),
            db=db,
        )

    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "nexus_identity_value_changed"
    await db.refresh(candidate)
    assert candidate.lastname == "Nowsza korekta"
    embed.assert_not_awaited()


class _OneEmployee:
    def __init__(
        self,
        external_id: str,
        *,
        name: str = "Anna Source",
        lastname: str = "Kowalska Source",
    ) -> None:
        self.external_id = external_id
        self.name = name
        self.lastname = lastname

    async def total_count(self, _path: str) -> int:
        return 1

    async def get_paginated(self, _path: str, *, page_size: int = 100, **_kwargs):
        return
        yield  # pragma: no cover - keeps this an async generator

    async def get_pages(
        self,
        _path: str,
        *,
        page_size: int = 100,
        filter_=None,
        start_page: int = 1,
        **_kwargs,
    ):
        yield (
            1,
            [
                {
                    "id": self.external_id,
                    "name": self.name,
                    "lastname": self.lastname,
                    "status": "active",
                    "updated_at": "2026-08-28 10:15:00",
                }
            ],
        )


@pytest.mark.asyncio
async def test_real_import_preserves_manual_name_and_updates_unlocked_lastname(
    db,
) -> None:
    from app.services.traffit.importer import TraffitImporter

    external_id = f"identity-{uuid.uuid4().hex}"
    candidate = Candidate(
        name="Anna Manual",
        lastname="Kowalska Old",
        external_source="traffit",
        external_id=external_id,
        custom_fields={
            "tenant_field": "preserved",
            "_nexus_identity": {
                "name_manual": True,
                "traffit_name": "Anna Old Source",
                "traffit_lastname": "Kowalska Old",
            },
        },
    )
    db.add(candidate)
    await db.commit()
    candidate_id = candidate.id

    progress = await TraffitImporter(
        _OneEmployee(external_id),
        db,
        dry_run=False,
        batch_size=10,
    ).import_candidates(since=None)

    assert progress.errors == 0, progress.error_samples
    result = await db.execute(
        select(Candidate)
        .execution_options(populate_existing=True)
        .where(Candidate.id == candidate_id)
    )
    imported = result.scalar_one()
    assert imported.name == "Anna Manual"
    assert imported.lastname == "Kowalska Source"
    assert imported.custom_fields["tenant_field"] == "preserved"
    metadata = imported.custom_fields["_nexus_identity"]
    assert metadata["name_manual"] is True
    assert metadata["traffit_name"] == "Anna Source"
    assert metadata["traffit_lastname"] == "Kowalska Source"
    assert metadata["traffit_source_updated_at"] == "2026-08-28T10:15:00+00:00"


@pytest.mark.asyncio
async def test_first_sync_preserves_legacy_mismatch_for_manual_review(db) -> None:
    from app.services.traffit.importer import TraffitImporter

    external_id = f"identity-bootstrap-{uuid.uuid4().hex}"
    candidate = Candidate(
        name="Anna Source",
        lastname="Kowalska bez projektu",
        external_source="traffit",
        external_id=external_id,
        custom_fields={"tenant_field": "preserved"},
    )
    db.add(candidate)
    await db.commit()
    candidate_id = candidate.id

    progress = await TraffitImporter(
        _OneEmployee(external_id),
        db,
        dry_run=False,
        batch_size=10,
    ).import_candidates(since=None)

    assert progress.errors == 0, progress.error_samples
    result = await db.execute(
        select(Candidate)
        .execution_options(populate_existing=True)
        .where(Candidate.id == candidate_id)
    )
    imported = result.scalar_one()
    assert imported.name == "Anna Source"
    assert imported.lastname == "Kowalska bez projektu"
    assert imported.custom_fields["tenant_field"] == "preserved"
    metadata = imported.custom_fields["_nexus_identity"]
    assert "name_manual" not in metadata
    assert metadata["lastname_manual"] is True
    assert metadata["lastname_ownership_reason"] == "bootstrap_mismatch"
    assert metadata["traffit_lastname"] == "Kowalska Source"
    assert isinstance(metadata["lastname_set_at"], str)


@pytest.mark.asyncio
async def test_first_sync_still_applies_known_traffit_marker_cleanup(db) -> None:
    from app.services.traffit.importer import TraffitImporter

    external_id = f"identity-bootstrap-marker-{uuid.uuid4().hex}"
    candidate = Candidate(
        name="Anna active",
        lastname="Kowalska",
        external_source="traffit",
        external_id=external_id,
        custom_fields={},
    )
    db.add(candidate)
    await db.commit()
    candidate_id = candidate.id

    progress = await TraffitImporter(
        _OneEmployee(external_id, name="Anna active", lastname="Kowalska"),
        db,
        dry_run=False,
        batch_size=10,
    ).import_candidates(since=None)

    assert progress.errors == 0, progress.error_samples
    result = await db.execute(
        select(Candidate)
        .execution_options(populate_existing=True)
        .where(Candidate.id == candidate_id)
    )
    imported = result.scalar_one()
    assert imported.name == "Anna"
    metadata = imported.custom_fields["_nexus_identity"]
    assert metadata["traffit_name"] == "Anna"
    assert "name_manual" not in metadata
    assert "name_ownership_reason" not in metadata


@pytest.mark.asyncio
async def test_adopt_path_preserves_lock_and_refreshes_source_snapshot(db) -> None:
    from app.services.traffit.importer import _UPDATE_CANDIDATE_ADOPT

    suffix = uuid.uuid4().hex
    candidate = Candidate(
        name="Anna Manual",
        lastname="Kowalska Old",
        external_source="talent_radar",
        external_id=f"legacy-{suffix}",
        custom_fields={
            "tenant_field": "preserved",
            "_nexus_identity": {
                "name_manual": True,
                "name_set_at": "2026-08-28T09:00:00+00:00",
                "name_set_by": 17,
                "name_ownership_reason": "manual_edit",
            },
        },
    )
    db.add(candidate)
    await db.commit()

    await db.execute(
        _UPDATE_CANDIDATE_ADOPT,
        {
            "nexus_id": candidate.id,
            "external_id": f"adopted-{suffix}",
            "external_source": "traffit",
            "name": "Anna Source",
            "lastname": "Kowalska Source",
            "traffit_raw_name": "Anna Source",
            "traffit_raw_lastname": "Kowalska Source",
            "traffit_source_updated_at": "2026-08-28T10:15:00+00:00",
            "phone": None,
            "linkedin": None,
            "status": "active",
            "profile_about": None,
            "cv_filename": None,
            "cv_extracted_data": "{}",
        },
    )
    await db.commit()

    result = await db.execute(
        select(Candidate)
        .execution_options(populate_existing=True)
        .where(Candidate.id == candidate.id)
    )
    adopted = result.scalar_one()
    assert adopted.external_source == "traffit"
    assert adopted.name == "Anna Manual"
    assert adopted.lastname == "Kowalska Old"
    assert adopted.custom_fields["tenant_field"] == "preserved"
    metadata = adopted.custom_fields["_nexus_identity"]
    assert metadata["name_manual"] is True
    assert metadata["name_set_at"] == "2026-08-28T09:00:00+00:00"
    assert metadata["name_set_by"] == 17
    assert metadata["name_ownership_reason"] == "manual_edit"
    assert metadata["lastname_manual"] is True
    assert metadata["lastname_ownership_reason"] == "bootstrap_mismatch"
    assert metadata["traffit_name"] == "Anna Source"
    assert metadata["traffit_lastname"] == "Kowalska Source"
    assert metadata["traffit_source_updated_at"] == "2026-08-28T10:15:00+00:00"
