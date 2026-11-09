"""Drugi dokument z bajtami pliku z kwarantanny nie jest bieżącym CV (Postgres).

Pomiar 05.11.2026: 17 żywych dokumentów w 16 profilach ma bajty pliku z kwarantanny,
a filtr patrzył tylko na id dokumentu. Żadna para nie ma obu skrótów, bo
`ux_candidate_documents_candidate_sha` nie pozwala na dwa takie same w jednym
profilu, więc o kopii mówią dopiero bajty. Dane fikcyjne.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_source_identity_review import (
    CandidateSourceIdentityReview,
)
from app.models.user import User, UserRole
from app.services import cv_source, object_storage
from app.services.candidate_identity_quarantine import (
    override_identity_quarantine,
)
from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    load_candidate_generation_source,
)

pytestmark = pytest.mark.asyncio

FOREIGN_FILE = b"%PDF-1.4 fikcyjne CV innej osoby"
OWN_FILE = b"%PDF-1.4 fikcyjne CV wlasciciela profilu"
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


async def _profile(*, pointer: bytes | None = None) -> int:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Anna",
            lastname=f"Fikcyjna{uuid.uuid4().hex[:8]}",
            cv_file_content=pointer,
            cv_filename="wskaznik.pdf" if pointer else None,
            cv_extracted_data={},
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _document(
    candidate_id: int,
    content: bytes,
    *,
    filename: str = "cv.pdf",
    age_days: int = 0,
    primary: bool = False,
    stored_hash: bool = False,
) -> int:
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=candidate_id,
            filename=filename,
            file_content=content,
            content_sha256=hashlib.sha256(content).hexdigest() if stored_hash else None,
            document_kind=CandidateDocumentKind.cv,
            is_primary=primary,
            uploaded_at=NOW - timedelta(days=age_days),
        )
        db.add(document)
        await db.commit()
        return document.id


async def _review(candidate_id: int, document_id: int, **fields: object) -> None:
    values = {
        "decision": "confirmed_mismatch",
        "provenance": "cv_parser:document",
        "detector_version": "test",
        "evidence": {},
        "reviewed_at": NOW,
        **fields,
    }
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSourceIdentityReview(
                candidate_id=candidate_id,
                source_kind="document",
                source_id=document_id,
                **values,
            )
        )
        await db.commit()


async def _quarantined(candidate_id: int, content: bytes = FOREIGN_FILE) -> int:
    document_id = await _document(
        candidate_id, content, filename="cudze.pdf", age_days=30
    )
    await _review(candidate_id, document_id)
    return document_id


async def _release(candidate_id: int, document_id: int) -> None:
    async with AsyncSessionLocal() as db:
        actor = User(
            email=f"hor-{uuid.uuid4().hex[:8]}@example.test",
            password_hash="x",
            name="Fikcyjny HoR",
            role=UserRole.head_of_recruitment,
            roles=[UserRole.head_of_recruitment.value],
            is_active=True,
        )
        db.add(actor)
        await db.flush()
        await override_identity_quarantine(
            db,
            candidate_id=candidate_id,
            source_kind="document",
            source_id=document_id,
            actor=actor,
            reason="Sprawdzone z kandydatem",
        )
        await db.commit()


async def _current(candidate_id: int) -> cv_source.CurrentCV | None:
    async with AsyncSessionLocal() as db:
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == candidate_id)
        )
        return await cv_source.get_current_cv(db, candidate)


async def test_copy_gives_way_to_the_persons_other_file() -> None:
    candidate_id = await _profile()
    await _quarantined(candidate_id)
    await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf", age_days=0)
    await _document(candidate_id, OWN_FILE, filename="wlasne.pdf", age_days=10)

    current = await _current(candidate_id)

    assert current is not None and current.filename == "wlasne.pdf"
    assert current.content == OWN_FILE


async def test_copy_marked_primary_does_not_win() -> None:
    candidate_id = await _profile()
    await _quarantined(candidate_id)
    await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf", primary=True)
    await _document(candidate_id, OWN_FILE, filename="wlasne.pdf", age_days=10)

    current = await _current(candidate_id)

    assert current is not None and current.filename == "wlasne.pdf"


async def test_copy_with_a_stored_hash_is_found_by_the_quarantined_files_bytes() -> (
    None
):
    candidate_id = await _profile()
    await _quarantined(candidate_id)
    await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf", stored_hash=True)

    assert await _current(candidate_id) is None


async def test_only_copy_comes_back_after_release_of_the_quarantined_file() -> None:
    candidate_id = await _profile()
    quarantined_id = await _quarantined(candidate_id)
    await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf")

    assert await _current(candidate_id) is None

    await _release(candidate_id, quarantined_id)

    current = await _current(candidate_id)
    assert current is not None and current.filename == "kopia.pdf"


async def test_copy_with_its_own_release_stays_current() -> None:
    candidate_id = await _profile()
    await _quarantined(candidate_id)
    copy_id = await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf")
    await _review(candidate_id, copy_id)
    await _release(candidate_id, copy_id)

    current = await _current(candidate_id)

    assert current is not None and current.filename == "kopia.pdf"


async def test_copy_read_as_this_person_stays_current() -> None:
    candidate_id = await _profile()
    await _quarantined(candidate_id)
    copy_id = await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf")
    await _review(candidate_id, copy_id, decision="confirmed_match")

    current = await _current(candidate_id)

    assert current is not None and current.filename == "kopia.pdf"


async def test_other_file_of_a_quarantined_profile_stays_current() -> None:
    candidate_id = await _profile()
    await _quarantined(candidate_id)
    await _document(candidate_id, OWN_FILE, filename="wlasne.pdf")

    current = await _current(candidate_id)

    assert current is not None and current.filename == "wlasne.pdf"


async def test_unreadable_quarantined_file_does_not_hide_the_persons_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(_key: str) -> bytes:
        raise OSError("magazyn niedostepny")

    candidate_id = await _profile()
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=candidate_id,
            filename="cudze.pdf",
            storage_key=f"cv/{uuid.uuid4().hex}.pdf",
            document_kind=CandidateDocumentKind.cv,
            is_primary=False,
            uploaded_at=NOW,
        )
        db.add(document)
        await db.commit()
        quarantined_id = document.id
    await _review(candidate_id, quarantined_id)
    await _document(candidate_id, OWN_FILE, filename="wlasne.pdf")
    monkeypatch.setattr(object_storage, "download_cv", broken)

    current = await _current(candidate_id)

    assert current is not None and current.filename == "wlasne.pdf"


async def test_profile_without_quarantine_reads_no_file_to_compare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id = await _profile()
    await _document(candidate_id, OWN_FILE)
    download = AsyncMock()
    monkeypatch.setattr(object_storage, "download_cv", download)

    async with AsyncSessionLocal() as db:
        assert await cv_source.quarantined_copy_document_ids(db, candidate_id) == (
            frozenset()
        )

    download.assert_not_called()


async def test_generator_default_skips_the_copy() -> None:
    candidate_id = await _profile()
    await _quarantined(candidate_id)
    await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf")

    async with AsyncSessionLocal() as db:
        with pytest.raises(StandaloneGenerationError) as refused:
            await load_candidate_generation_source(
                db, candidate_id=candidate_id, stage_id=None
            )

    assert refused.value.code == "no_cv_file"


async def test_copy_cannot_become_the_stage_original(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    from tests.test_stage_cv_upload import _from_document, _stage_with_snapshot

    candidate_id, stage_id = await _stage_with_snapshot()
    await _quarantined(candidate_id)
    copy_id = await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf")

    res = await _from_document(app_client, app_auth_headers, stage_id, copy_id)

    assert res.status_code == 409, res.text


async def test_ai_sources_mark_the_copy_like_the_quarantined_file() -> None:
    from types import SimpleNamespace

    from app.api.cv_ai_sources import _cv_files

    candidate_id = await _profile()
    await _quarantined(candidate_id)
    copy_id = await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf")
    own_id = await _document(candidate_id, OWN_FILE, filename="wlasne.pdf", age_days=10)

    async with AsyncSessionLocal() as db:
        files = await _cv_files(
            db, SimpleNamespace(id=0, candidate_id=candidate_id, job_id=0)
        )

    outdated = {file.document_id: file.outdated for file in files}
    assert outdated[copy_id] is True
    assert outdated[own_id] is False


async def test_reread_of_a_primary_copy_does_not_reach_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import candidates as candidates_api

    candidate_id = await _profile()
    await _quarantined(candidate_id)
    copy_id = await _document(
        candidate_id, FOREIGN_FILE, filename="kopia.pdf", primary=True
    )
    parse = AsyncMock(return_value={"first_name": "?", "last_name": "?"})
    monkeypatch.setattr("app.services.cv_parser.parse_cv", parse)
    monkeypatch.setattr(
        "app.services.cv_text_extractor.extract_text",
        lambda *_args, **_kwargs: "Fikcyjny tekst CV innej osoby",
    )

    await candidates_api._enrich_candidate_from_document_task(
        candidate_id, copy_id, None, force_read=True
    )

    parse.assert_not_called()
    async with AsyncSessionLocal() as db:
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == candidate_id)
        )
    assert candidate.raw_cv_text is None


async def test_backfill_gate_stops_a_copy_with_a_stored_hash() -> None:
    from app.services.cv_backfill import _identity_quarantined

    candidate_id = await _profile()
    await _quarantined(candidate_id)
    await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf", stored_hash=True)

    async with AsyncSessionLocal() as db:
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == candidate_id)
        )
        blocked, document_id = await _identity_quarantined(
            db,
            candidate,
            hashlib.sha256(FOREIGN_FILE).hexdigest(),
            {"first_name": "?", "last_name": "?"},
        )

    assert (blocked, document_id) == (True, None)


async def test_integration_api_does_not_serve_the_copy() -> None:
    from app.services import integration_candidate_reads as reads

    candidate_id = await _profile()
    await _quarantined(candidate_id)
    copy_id = await _document(candidate_id, FOREIGN_FILE, filename="kopia.pdf")
    own_id = await _document(candidate_id, OWN_FILE, filename="wlasne.pdf")

    async with AsyncSessionLocal() as db:
        listed = await reads.list_documents(db, candidate_id)
        copy = await reads.load_document(db, candidate_id, copy_id)
        own = await reads.load_document(db, candidate_id, own_id)

    assert [document.id for document in listed] == [own_id]
    assert copy is None
    assert own is not None
