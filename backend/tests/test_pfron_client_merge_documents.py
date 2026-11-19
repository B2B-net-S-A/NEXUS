"""Dokończenie scalenia PFRON 58469 → 122: dokumenty przechodzą, potem flaga (19.11.2026).

Pierwszy bieg zostawił na duplikacie wygenerowane CV, więc scalenie nie
ukryło rekordu. Drugi bieg przepina dokumenty i dopiero wtedy ustawia flagę.
Pominięty bieg (zła tożsamość) nie zostawia znacznika.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client import Client
from app.models.cv_generated_document import CvGeneratedDocument
from scripts.repairs.cardif_client_merge_repair import CardifMergeTarget
from scripts.repairs.run_repair_pfron_client_merge_documents import (
    MARKER,
    run_pfron_documents_merge,
)
from tests.test_cardif_client_merge_repair import _pair

pytestmark = pytest.mark.asyncio


def test_marker_is_distinct_from_the_first_run():
    assert MARKER == "0738_pfron_client_merge_documents"


async def _cv_document(client_id: int) -> int:
    async with AsyncSessionLocal() as db:
        doc = CvGeneratedDocument(
            client_id=client_id, candidate_name="Kandydat Testowy", filename="cv.pdf"
        )
        db.add(doc)
        await db.commit()
        return doc.id


async def test_documents_move_then_duplicate_is_merged():
    canonical, source, token = await _pair()
    doc_id = await _cv_document(source)
    target = CardifMergeTarget(source_id=source, target_id=canonical, name_token=token)
    marker = f"test_pfron_docs_{token}"

    async with AsyncSessionLocal() as db:
        summary = await run_pfron_documents_merge(db, target=target, marker=marker)
        await db.commit()

    assert summary["documents_moved"]["cv_generated_documents"] == 1
    assert summary["merged"] is True and summary["unexpected_references"] == {}
    async with AsyncSessionLocal() as db:
        assert (await db.get(CvGeneratedDocument, doc_id)).client_id == canonical
        assert (await db.get(Client, source)).merged_into_client_id == canonical
        assert await db.get(AppSetting, marker) is not None
    async with AsyncSessionLocal() as db:
        assert await run_pfron_documents_merge(db, target=target, marker=marker) is None


async def test_identity_mismatch_moves_nothing_and_leaves_no_marker():
    canonical, source, token = await _pair()
    doc_id = await _cv_document(source)
    target = CardifMergeTarget(
        source_id=source, target_id=canonical, name_token="nie-ta-nazwa"
    )
    marker = f"test_pfron_docs_skip_{token}"

    async with AsyncSessionLocal() as db:
        summary = await run_pfron_documents_merge(db, target=target, marker=marker)
        await db.commit()

    assert summary["skipped"] == "identity_mismatch"
    assert summary["documents_moved"] == {}
    async with AsyncSessionLocal() as db:
        assert (await db.get(CvGeneratedDocument, doc_id)).client_id == source
        assert await db.get(AppSetting, marker) is None
        assert (
            await db.scalar(
                select(Client.merged_into_client_id).where(Client.id == source)
            )
            is None
        )
