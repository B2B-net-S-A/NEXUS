"""Restoring a source must not promote it before the identity gate flushes."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.services import candidate_identity_quarantine, cv_enrichment, cv_parser
from app.services import cv_text_extractor
from app.services.m365 import attachment_handler


@pytest.mark.asyncio
@pytest.mark.parametrize("source_state", ["deleted", "reclassified", "rematched"])
@pytest.mark.parametrize("quarantined", [False, True])
async def test_restored_primary_waits_for_identity_gate(
    monkeypatch, tmp_path, source_state, quarantined
):
    now = datetime.now(timezone.utc)
    ext_id = f"m365-primary-{uuid.uuid4().hex}"
    content = b"Synthetic Alex Example CV"
    (tmp_path / "synthetic.pdf").write_bytes(content)
    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(attachment_handler.settings, "M365_AUTO_PARSE_CV", True)
    monkeypatch.setattr(cv_text_extractor, "extract_text", lambda *_: "Synthetic CV")
    monkeypatch.setattr(
        cv_parser,
        "parse_cv",
        AsyncMock(return_value={"first_name": "Alex", "last_name": "Example"}),
    )
    enrichment = MagicMock()
    monkeypatch.setattr(cv_enrichment, "_apply_cv_enrichment", enrichment)

    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Alex", lastname="Example", raw_cv_text="Existing trusted CV"
        )
        former_owner = Candidate(name="Other", lastname="Example")
        db.add_all([candidate, former_owner])
        await db.flush()
        current = CandidateDocument(
            candidate_id=candidate.id,
            filename="current.pdf",
            file_content=b"Current synthetic CV",
            content_type="application/pdf",
            size_bytes=20,
            document_kind=CandidateDocumentKind.cv,
            is_primary=True,
        )
        restored = CandidateDocument(
            candidate_id=(
                former_owner.id if source_state == "rematched" else candidate.id
            ),
            filename="synthetic.pdf",
            file_content=content,
            content_type="application/pdf",
            size_bytes=len(content),
            document_kind=(
                CandidateDocumentKind.other
                if source_state == "reclassified"
                else CandidateDocumentKind.cv
            ),
            is_primary=True,
            source_deleted_at=(now if source_state == "deleted" else None),
            external_source="m365",
            external_id=ext_id,
        )
        db.add_all([current, restored])
        await db.flush()

        async def identity_gate(session, **kwargs):
            assert kwargs["source_id"] == restored.id
            # Match the real gate's flush: the previous code fails the actual
            # active-primary unique index here, before it can make a decision.
            await session.flush()
            active_primary_ids = list(
                await session.scalars(
                    select(CandidateDocument.id).where(
                        CandidateDocument.candidate_id == candidate.id,
                        CandidateDocument.is_primary.is_(True),
                        CandidateDocument.source_deleted_at.is_(None),
                        CandidateDocument.document_kind == CandidateDocumentKind.cv,
                    )
                )
            )
            assert active_primary_ids == [current.id]
            return SimpleNamespace(is_quarantined=quarantined)

        monkeypatch.setattr(
            candidate_identity_quarantine, "record_detected_identity", identity_gate
        )
        attachment = SimpleNamespace(
            id=1,
            is_cv_candidate=True,
            storage_path="synthetic.pdf",
            filename="synthetic.pdf",
            content_type="application/pdf",
            sha256=None,
            m365_attachment_id=ext_id,
            parsed_candidate_id=None,
            parse_error=None,
        )
        email = SimpleNamespace(
            candidate_id=candidate.id, received_at=now - timedelta(days=1)
        )
        await attachment_handler.try_parse_cv(db, attachment, email)
        await db.flush()
        await db.refresh(current)
        await db.refresh(restored)
        assert db.is_active
        assert restored.source_deleted_at is None
        assert restored.candidate_id == candidate.id
        assert restored.is_primary is (not quarantined)
        assert current.is_primary is quarantined
        assert attachment.parsed_candidate_id == candidate.id
        if quarantined:
            assert attachment.parse_error == "identity_mismatch_quarantined"
            assert candidate.raw_cv_text == "Existing trusted CV"
            enrichment.assert_not_called()
        else:
            assert attachment.parse_error is None
            assert candidate.raw_cv_text == "Synthetic CV"
            enrichment.assert_called_once()
        # Everything is synthetic and left uncommitted: close rolls it back.


@pytest.mark.asyncio
async def test_already_applied_attachment_is_not_parsed_again(monkeypatch):
    """Delta pages must not pay for and reapply the same CV on every pass."""
    monkeypatch.setattr(attachment_handler.settings, "M365_AUTO_PARSE_CV", True)
    db = AsyncMock()
    attachment = SimpleNamespace(
        parsed_candidate_id=37,
        is_cv_candidate=True,
        storage_path="already-applied.pdf",
        cv_parse_attempted_at=datetime.now(timezone.utc),
    )
    email = SimpleNamespace(candidate_id=37)

    await attachment_handler.try_parse_cv(db, attachment, email)

    db.scalar.assert_not_awaited()
    db.get.assert_not_awaited()
