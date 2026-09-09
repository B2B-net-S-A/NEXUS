"""Hosted PostgreSQL proof for the raw SQL import source-update boundary."""

import json
import uuid

import pytest

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from app.services.traffit.importer import _UPSERT_JOB
from app.services.traffit.mappers import traffit_recruitment_to_job


@pytest.mark.asyncio
@pytest.mark.parametrize("new_title", ["Python Developer", "Java Developer"])
async def test_import_title_change_invalidates_review_but_identical_sync_preserves_it(
    new_title,
):
    async with AsyncSessionLocal() as db:
        try:
            external_id = uuid.uuid4().hex
            client = Client(name=f"Import review {external_id}")
            db.add(client)
            await db.flush()
            reviewed_empty = {
                "version": 1,
                "reviewed": True,
                "all_of": [],
                "missing_evidence_policy": "review",
            }
            job = Job(
                title="Python Developer",
                client_id=client.id,
                external_source="traffit",
                external_id=external_id,
                matching_requirements=reviewed_empty,
                requirements_reviewed=True,
            )
            db.add(job)
            await db.flush()
            before = build_request_context(job, DEFAULT_PROFILE)
            payload = traffit_recruitment_to_job(
                {
                    "id": external_id,
                    "name": new_title,
                    "client": {"id": 7},
                    "is_confidential": True,
                },
                {"7": client.id},
                {},
            )
            payload["custom_fields"] = json.dumps(payload["custom_fields"])
            await db.execute(_UPSERT_JOB, payload)
            await db.refresh(job)
            assert job.title == new_title
            after = build_request_context(job, DEFAULT_PROFILE)
            if new_title == "Python Developer":
                assert job.matching_requirements == reviewed_empty
                assert job.requirements_reviewed is True
                assert before.fingerprint == after.fingerprint
            else:
                assert job.matching_requirements is None
                assert job.requirements_reviewed is False
                assert before.fingerprint != after.fingerprint
        finally:
            await db.rollback()
