"""PostgreSQL ownership, capacity and approval transaction boundaries."""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib

import pytest
from sqlalchemy import delete, update

from app.core.database import AsyncSessionLocal
from app.models.cv_document_version import CvDocumentVersion
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_version_map import CvVersionMap
from app.services.cv_version_map_jobs import claim_map, enqueue_version_map, finish_map


async def create_version(db, owner, number):
    html = "<p>AWS wyłącznie szkoleniowo.</p>"
    version = CvDocumentVersion(
        generated_owner_id=owner,
        generated_document_id=owner,
        version=number,
        content_html=html,
        content_sha256=hashlib.sha256(html.encode()).hexdigest(),
        language="pl",
        approved_at=datetime.now(timezone.utc),
    )
    db.add(version)
    await db.flush()
    await enqueue_version_map(db, version, [{"name": "AWS", "kind": "must"}], None)
    return version.id


@pytest.fixture
async def map_owner():
    async with AsyncSessionLocal() as db:
        doc = CvGeneratedDocument(
            candidate_name="Synthetic map test",
            filename="test.docx",
            mode="upload",
            status="ready",
        )
        db.add(doc)
        await db.commit()
        owner = doc.id
    try:
        yield owner
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CvGeneratedDocument).where(CvGeneratedDocument.id == owner)
            )
            await db.commit()


async def test_map_and_approval_rollback_and_cascade_together(map_owner):
    async with AsyncSessionLocal() as db:
        rolled_back = await create_version(db, map_owner, 1)
        await db.rollback()
    async with AsyncSessionLocal() as db:
        assert await db.get(CvDocumentVersion, rolled_back) is None
        assert await db.get(CvVersionMap, rolled_back) is None
        kept = await create_version(db, map_owner, 1)
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert (await db.get(CvVersionMap, kept)).status == "queued"
        await db.execute(delete(CvDocumentVersion).where(CvDocumentVersion.id == kept))
        await db.commit()
    async with AsyncSessionLocal() as db:
        assert await db.get(CvVersionMap, kept) is None


async def test_concurrent_claims_enforce_global_capacity_and_single_owner(map_owner):
    async with AsyncSessionLocal() as db:
        ids = [await create_version(db, map_owner, i) for i in range(1, 4)]
        await db.commit()

    async def claim(key):
        async with AsyncSessionLocal() as db:
            return await claim_map(db, key)

    tokens = await asyncio.gather(*(claim(key) for key in ids))
    assert sum(token is not None for token in tokens) == 2
    owned_id = next(key for key, token in zip(ids, tokens) if token)
    assert await claim(owned_id) is None
    for key, token in zip(ids, tokens):
        if token:
            async with AsyncSessionLocal() as db:
                await finish_map(db, key, token, error="test_finished")
    queued_id = next(key for key, token in zip(ids, tokens) if token is None)
    last_token = await claim(queued_id)
    assert last_token is not None
    async with AsyncSessionLocal() as db:
        await finish_map(db, queued_id, last_token, result={"items": []})
    async with AsyncSessionLocal() as db:
        row = await db.get(CvVersionMap, queued_id)
        assert row.status == "complete" and row.result == {"items": []}
        assert row.input_content is None and row.lease_token is None


async def test_wrong_and_expired_lease_cannot_publish_or_clear_input(map_owner):
    async with AsyncSessionLocal() as db:
        key = await create_version(db, map_owner, 1)
        await db.commit()
        token = await claim_map(db, key)
        assert token
        await finish_map(db, key, "wrong-token", result={"items": []})
    async with AsyncSessionLocal() as db:
        row = await db.get(CvVersionMap, key)
        assert row.status == "running" and row.input_content is not None
        await db.execute(
            update(CvVersionMap)
            .where(CvVersionMap.document_version_id == key)
            .values(lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        )
        await db.commit()
        await finish_map(db, key, token, result={"items": []})
    async with AsyncSessionLocal() as db:
        row = await db.get(CvVersionMap, key)
        assert row.status == "running" and row.input_content is not None
        assert row.result is None
