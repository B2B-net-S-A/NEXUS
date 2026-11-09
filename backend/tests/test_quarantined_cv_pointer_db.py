"""Kopia pliku z kwarantanny pod `cv_storage_key` nie wraca do profilu (Postgres).

Pomiar 05.11.2026: klucz wskaźnika nie jest kluczem dokumentu w żadnej z 254
aktywnych kwarantann plików, ale 66 wskaźników trzyma te same bajty, a 54 z tych
dokumentów nie ma zapisanego `content_sha256`. Pozostałe 177 wskaźników to inny
plik, więc wskaźnika nie wolno po prostu zdjąć. Dane fikcyjne.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_source_identity_review import (
    CandidateSourceIdentityReview,
)
from app.models.user import User, UserRole
from app.services import cv_backfill, cv_source, cv_text_backfill, object_storage
from app.services.candidate_identity_quarantine import (
    override_identity_quarantine,
)
from app.services.must_text_evidence import cv_waiting_for_text

pytestmark = pytest.mark.asyncio

FOREIGN_FILE = b"%PDF-1.4 fikcyjne CV innej osoby"
OWN_FILE = b"%PDF-1.4 fikcyjne CV wlasciciela profilu"
FILE_TEXT = "Fikcyjne doswiadczenie zawodowe w projektach. " * 20
POINTER_KEY = "cv/2026/11/wskaznik.pdf"
DOCUMENT_KEY = "cv/2026/11/dokument.pdf"
MARKER = cv_text_backfill._EXTRACTION_MARKER_KEY
_PENDING_STMT = cv_text_backfill._pending_candidates_stmt
_GLUED_STMT = cv_text_backfill._glued_candidates_stmt


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture
def stored_files(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    files = {POINTER_KEY: FOREIGN_FILE, DOCUMENT_KEY: FOREIGN_FILE}

    def download(key: str) -> bytes:
        return files[key]

    monkeypatch.setattr(cv_text_backfill, "download_cv", download)
    monkeypatch.setattr(object_storage, "download_cv", download)
    monkeypatch.setattr(cv_text_backfill, "is_available", lambda: True)
    monkeypatch.setattr(cv_text_backfill, "sniff_extension", lambda _path: ".pdf")
    monkeypatch.setattr(cv_text_backfill, "extract_cv_text", lambda *_a: FILE_TEXT)
    return files


async def _profile(*, raw_cv_text: str | None = None, name: str = "Anna") -> int:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name=name,
            lastname=f"Fikcyjna{uuid.uuid4().hex[:8]}",
            cv_storage_key=POINTER_KEY,
            raw_cv_text=raw_cv_text,
            cv_extracted_data={},
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _quarantined_document(candidate_id: int, *, stored_hash: bool = True) -> int:
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=candidate_id,
            filename="cv-innej-osoby.pdf",
            storage_key=DOCUMENT_KEY,
            content_sha256=_sha(FOREIGN_FILE) if stored_hash else None,
            document_kind=CandidateDocumentKind.cv,
            is_primary=False,
            uploaded_at=now,
        )
        db.add(document)
        await db.flush()
        db.add(
            CandidateSourceIdentityReview(
                candidate_id=candidate_id,
                source_kind="document",
                source_id=document.id,
                decision="confirmed_mismatch",
                provenance="cv_parser:test",
                detector_version="test",
                evidence={},
                reviewed_at=now,
            )
        )
        await db.commit()
        return document.id


async def _reload(candidate_id: int) -> Candidate:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Candidate).where(Candidate.id == candidate_id))


async def _run_backfill(
    monkeypatch: pytest.MonkeyPatch, candidate_id: int, *, glued: bool = False
) -> cv_text_backfill.BackfillStats:
    """Prawdziwy predykat biegu, zawężony do jednej osoby ze wspólnej bazy."""
    monkeypatch.setattr(
        cv_text_backfill,
        "_pending_candidates_stmt",
        lambda _limit, **kwargs: _PENDING_STMT(None, **kwargs).where(
            Candidate.id == candidate_id
        ),
    )
    monkeypatch.setattr(
        cv_text_backfill,
        "_glued_candidates_stmt",
        lambda _limit: _GLUED_STMT(None).where(Candidate.id == candidate_id),
    )
    return await cv_text_backfill.run_backfill(
        commit=True, enqueue_reindex=False, glued=glued
    )


@pytest.mark.parametrize("stored_hash", [True, False])
async def test_backfill_does_not_restore_text_from_a_copy_of_the_quarantined_file(
    monkeypatch: pytest.MonkeyPatch, stored_files: dict[str, bytes], stored_hash: bool
) -> None:
    candidate_id = await _profile()
    await _quarantined_document(candidate_id, stored_hash=stored_hash)

    stats = await _run_backfill(monkeypatch, candidate_id)

    candidate = await _reload(candidate_id)
    assert candidate.raw_cv_text is None
    assert stats.quarantined == 1
    assert stats.extracted == 0
    assert stats.candidate_ids_written == []
    assert candidate.cv_extracted_data[MARKER]["outcome"] == "quarantined"
    assert candidate.cv_extracted_data[MARKER]["storage_key"] == POINTER_KEY
    # Wyrok końcowy: następny bieg nie pobiera tego pliku ponownie, a kandydat
    # nie wygląda na takiego, który czeka na odczyt.
    assert (await _run_backfill(monkeypatch, candidate_id)).scanned == 0
    assert cv_waiting_for_text(candidate) is False


async def test_backfill_reads_a_pointer_with_other_bytes(
    monkeypatch: pytest.MonkeyPatch, stored_files: dict[str, bytes]
) -> None:
    """177 z 243 wskaźników to inny plik: kwarantanna dokumentu ich nie dotyczy."""
    stored_files[POINTER_KEY] = OWN_FILE
    candidate_id = await _profile()
    await _quarantined_document(candidate_id)

    stats = await _run_backfill(monkeypatch, candidate_id)

    candidate = await _reload(candidate_id)
    assert candidate.raw_cv_text == FILE_TEXT.strip()
    assert stats.extracted == 1
    assert stats.quarantined == 0


async def test_new_file_under_the_pointer_is_read_despite_the_old_verdict(
    monkeypatch: pytest.MonkeyPatch, stored_files: dict[str, bytes]
) -> None:
    candidate_id = await _profile()
    await _quarantined_document(candidate_id)
    await _run_backfill(monkeypatch, candidate_id)

    stored_files["cv/2026/11/nowy.pdf"] = OWN_FILE
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        candidate.cv_storage_key = "cv/2026/11/nowy.pdf"
        await db.commit()

    await _run_backfill(monkeypatch, candidate_id)

    assert (await _reload(candidate_id)).raw_cv_text == FILE_TEXT.strip()


async def test_unreadable_unhashed_document_keeps_the_text_out(
    monkeypatch: pytest.MonkeyPatch, stored_files: dict[str, bytes]
) -> None:
    """Bez bajtów dokumentu nie da się wykluczyć kopii, więc tekst nie wchodzi."""
    del stored_files[DOCUMENT_KEY]
    candidate_id = await _profile()
    await _quarantined_document(candidate_id, stored_hash=False)

    stats = await _run_backfill(monkeypatch, candidate_id)

    assert (await _reload(candidate_id)).raw_cv_text is None
    assert stats.quarantined == 1


async def test_glued_run_keeps_own_text_and_leaves_the_scope(
    monkeypatch: pytest.MonkeyPatch, stored_files: dict[str, bytes]
) -> None:
    glued_text = "x" * 400
    candidate_id = await _profile(raw_cv_text=glued_text)
    await _quarantined_document(candidate_id)

    stats = await _run_backfill(monkeypatch, candidate_id, glued=True)

    candidate = await _reload(candidate_id)
    assert candidate.raw_cv_text == glued_text
    assert stats.quarantined == 1
    assert stats.improved == 0
    assert candidate.cv_extracted_data[MARKER]["outcome"] == "quarantined"
    assert (await _run_backfill(monkeypatch, candidate_id, glued=True)).scanned == 0


async def test_override_lets_the_released_file_be_read_again(
    monkeypatch: pytest.MonkeyPatch, stored_files: dict[str, bytes]
) -> None:
    candidate_id = await _profile()
    document_id = await _quarantined_document(candidate_id)
    await _run_backfill(monkeypatch, candidate_id)

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

    assert MARKER not in (await _reload(candidate_id)).cv_extracted_data
    stats = await _run_backfill(monkeypatch, candidate_id)

    assert stats.extracted == 1
    assert (await _reload(candidate_id)).raw_cv_text == FILE_TEXT.strip()


@pytest.mark.parametrize("stored_hash", [True, False])
async def test_current_cv_does_not_fall_back_to_a_copy_of_the_quarantined_file(
    stored_files: dict[str, bytes], stored_hash: bool
) -> None:
    """36 z 66 takich profili nie ma innego pliku: paczka CV i kopia etapu brały
    cudze CV."""
    candidate_id = await _profile()
    await _quarantined_document(candidate_id, stored_hash=stored_hash)

    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        assert await cv_source.get_current_cv(db, candidate) is None


async def test_current_cv_still_falls_back_to_a_pointer_with_other_bytes(
    stored_files: dict[str, bytes],
) -> None:
    stored_files[POINTER_KEY] = OWN_FILE
    candidate_id = await _profile()
    await _quarantined_document(candidate_id)

    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        current = await cv_source.get_current_cv(db, candidate)

    assert current is not None
    assert current.content == OWN_FILE
    assert current.source == "candidate_storage"


async def test_name_backfill_does_not_read_a_copy_of_an_unhashed_quarantined_file(
    monkeypatch: pytest.MonkeyPatch, stored_files: dict[str, bytes]
) -> None:
    """Bramka szukała dokumentu po skrócie, więc plik bez skrótu jej umykał, a przy
    imieniu `?` odczyt kończy się `inconclusive` i tekst trafiał do profilu."""

    async def text_of(*_args, **_kwargs) -> str:
        return FILE_TEXT

    async def parsed(*_args, **_kwargs) -> dict[str, str]:
        return {"first_name": "Inna", "last_name": "Osoba"}

    monkeypatch.setattr(cv_backfill, "_extract_text_from_bytes", text_of)
    monkeypatch.setattr(cv_backfill, "_parse_cv_for_names", parsed)
    candidate_id = await _profile(name="?")
    await _quarantined_document(candidate_id, stored_hash=False)

    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        result = await cv_backfill.backfill_candidate_from_stored_cv(db, candidate)
        await db.commit()

    assert result["identity_quarantined"] is True
    reloaded = await _reload(candidate_id)
    assert reloaded.raw_cv_text is None
    assert reloaded.name == "?"
