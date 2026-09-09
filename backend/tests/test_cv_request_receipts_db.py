"""Hosted PostgreSQL proof for concurrent enqueue receipts and rollback."""

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, func

from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generation_request import CvGenerationRequest
from app.services.cv_generator_b2b.request_receipts import reserve_request


async def test_preview_receipt_survives_retention_as_deleted_result():
    from fastapi import HTTPException
    from app.models.client import Client
    from app.models.client_cv_rule_preview import ClientCvRulePreview

    async with AsyncSessionLocal() as db:
        try:
            key = str(uuid4())
            user = User(
                email=f"preview-retry-{key}@example.test", name="Preview fixture"
            )
            client = Client(name=f"preview-{key}")
            db.add_all([user, client])
            await db.flush()
            preview = ClientCvRulePreview(client_id=client.id, created_by=user.id)
            db.add(preview)
            await db.flush()
            receipt, previous = await reserve_request(
                db, user.id, key, "preview", {"client_id": client.id}
            )
            assert previous is None
            receipt.preview_id = preview.id
            await db.flush()
            _, replay = await reserve_request(
                db, user.id, key, "preview", {"client_id": client.id}
            )
            assert replay.id == preview.id
            await db.execute(
                delete(ClientCvRulePreview).where(ClientCvRulePreview.id == preview.id)
            )
            await db.refresh(receipt)
            assert receipt.preview_id is None
            with pytest.raises(HTTPException) as error:
                await reserve_request(
                    db, user.id, key, "preview", {"client_id": client.id}
                )
            assert error.value.status_code == 410
        finally:
            await db.rollback()


@pytest.mark.parametrize("commit_first", [True, False])
async def test_competing_receipt_observes_commit_or_recovers_rollback(commit_first):
    key = str(uuid4())
    generated_ids = []
    async with AsyncSessionLocal() as seed:
        user = User(email=f"cv-retry-{key}@example.test", name="Retry fixture")
        seed.add(user)
        await seed.commit()
        user_id = user.id
    try:
        async with AsyncSessionLocal() as first, AsyncSessionLocal() as second:
            receipt, previous = await reserve_request(first, user_id, key, "new", {})
            assert previous is None
            document = CvGeneratedDocument(
                candidate_name="Retry fixture",
                filename="retry.docx",
                mode="upload",
                status="processing",
            )
            first.add(document)
            await first.flush()
            original_id = document.id
            generated_ids.append(original_id)
            receipt.generated_id = original_id
            await first.flush()
            competing = asyncio.create_task(
                reserve_request(second, user_id, key, "new", {})
            )
            try:
                # The held transaction lock must prevent a competing reservation.
                with pytest.raises(asyncio.TimeoutError):
                    await asyncio.wait_for(asyncio.shield(competing), timeout=0.1)
                if commit_first:
                    await first.commit()
                else:
                    await first.rollback()
                retried, replay = await asyncio.wait_for(competing, timeout=10)
                if commit_first:
                    assert replay.id == original_id
                    assert retried.generated_id == original_id
                else:
                    assert replay is None
                    assert retried.generated_id is None
                await second.commit()
            finally:
                if not competing.done():
                    competing.cancel()
                    await asyncio.gather(competing, return_exceptions=True)
        async with AsyncSessionLocal() as check:
            assert (
                await check.scalar(
                    select(func.count())
                    .select_from(CvGenerationRequest)
                    .where(
                        CvGenerationRequest.user_id == user_id,
                    )
                )
                == 1
            )
            assert (
                await check.get(CvGeneratedDocument, original_id) is not None
                if commit_first
                else await check.get(CvGeneratedDocument, original_id) is None
            )
    finally:
        async with AsyncSessionLocal() as cleanup:
            await cleanup.execute(delete(User).where(User.id == user_id))
            await cleanup.execute(
                delete(CvGeneratedDocument).where(
                    CvGeneratedDocument.id.in_(generated_ids)
                )
            )
            await cleanup.commit()
