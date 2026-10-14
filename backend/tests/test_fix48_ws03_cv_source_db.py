"""Audyt 48 h (13.10.2026), obszar WS03 — „bieżące CV” na Postgresie (CI).

* pkt 8: cudze CV w kwarantannie tożsamości zostawało bieżącym CV osoby, gdy
  nie miała innego — wracało do każdej następnej kopii CV etapu. Pierwsze
  sprzątanie kopii (`restore_stage_copies_after_quarantine`) czytało bazę
  sprzed decyzji (`autoflush=False`), więc kopia zostawała pusta także
  wtedy, gdy osoba miała poprzednie CV;
* po usunięciu głównego CV następcą bywał plik „nieaktualny” albo „…B2B…”;
* „Wgraj nowe CV” w rekrutacji przy awarii odczytu z magazynu: kopia etapu
  dostawała starsze CV ze wskaźnika kandydata pod nazwą nowego pliku.

Dane fikcyjne. Te same reguły bez bazy: `test_fix48_ws03_cv_source.py`.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.recruitment_pipeline import CandidateStage
from app.services.candidate_identity_quarantine import (
    ReplacedPrimaryCv,
    record_detected_identity,
)
from app.services.candidate_stage_cv_service import (
    create_original_cv_snapshot,
    snapshot_exists,
)
from app.services.cv_source import get_current_cv
from tests.test_candidate_stage_cv_snapshot import (
    _seed_candidate_with_cv,
    _seed_job,
    _seed_stage,
)

pytestmark = pytest.mark.asyncio

NEW_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"
)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def _candidate() -> int:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Anna", lastname=f"Fikcyjna{uuid.uuid4().hex[:8]}")
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _document(
    candidate_id: int,
    filename: str,
    content: bytes,
    *,
    primary: bool = False,
    age_days: int = 0,
    **extra,
) -> int:
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=candidate_id,
            filename=filename,
            file_content=content,
            content_sha256=_sha(content),
            document_kind=CandidateDocumentKind.cv,
            is_primary=primary,
            uploaded_at=datetime.now(timezone.utc) - timedelta(days=age_days),
            **extra,
        )
        db.add(document)
        await db.commit()
        return document.id


async def _stage_with_copy(candidate_id: int) -> int:
    stage_id = await _seed_stage(candidate_id, await _seed_job())
    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, stage_id)
        await create_original_cv_snapshot(db, stage)
        await db.commit()
    return stage_id


async def _copy(stage_id: int) -> CandidateStageCV:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_id
            )
        )


async def _quarantine(
    candidate_id: int, document_id: int, replaced: ReplacedPrimaryCv
) -> None:
    """Bramka tożsamości po wgraniu: odczytane imię i nazwisko innej osoby."""
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        review = await record_detected_identity(
            db,
            candidate=candidate,
            source_kind="document",
            source_id=document_id,
            observed_first_name="Zofia",
            observed_last_name="Przykladowa",
            provenance="test:fix48_ws03",
            replaced_primary=replaced,
        )
        assert review.is_quarantined
        await db.commit()


async def _current(candidate_id: int):
    async with AsyncSessionLocal() as db:
        return await get_current_cv(db, await db.get(Candidate, candidate_id))


async def test_quarantined_only_cv_does_not_reach_the_next_stage_copy() -> None:
    wrong = b"%PDF-1.4 CV innej osoby " + uuid.uuid4().hex.encode()
    cid = await _candidate()
    doc_id = await _document(cid, "cudze_cv.pdf", wrong, primary=True)
    first = await _stage_with_copy(cid)
    assert (await _copy(first)).original_cv_sha256 == _sha(wrong)

    await _quarantine(
        cid, doc_id, ReplacedPrimaryCv(document_id=None, cv_filename=None)
    )

    assert not snapshot_exists(await _copy(first))
    assert await _current(cid) is None
    # Ruch karty albo nowa rekrutacja: kopia z chwili zgłoszenia nie bierze
    # znowu cudzego pliku.
    later = await _stage_with_copy(cid)
    assert not snapshot_exists(await _copy(later))


async def test_quarantine_gives_stage_copy_the_previous_cv_of_the_person() -> None:
    own = b"%PDF-1.4 wlasne CV " + uuid.uuid4().hex.encode()
    wrong = b"%PDF-1.4 CV innej osoby " + uuid.uuid4().hex.encode()
    cid = await _candidate()
    previous_id = await _document(cid, "wlasne_cv.pdf", own, age_days=30)
    wrong_id = await _document(cid, "cudze_cv.pdf", wrong, primary=True)
    stage_id = await _stage_with_copy(cid)

    await _quarantine(
        cid,
        wrong_id,
        ReplacedPrimaryCv(document_id=previous_id, cv_filename="wlasne_cv.pdf"),
    )

    copy = await _copy(stage_id)
    assert copy.original_snapshot_source == "quarantine_restore"
    assert copy.original_cv_sha256 == _sha(own)
    assert copy.original_cv_filename == "wlasne_cv.pdf"
    current = await _current(cid)
    assert current is not None and current.filename == "wlasne_cv.pdf"


async def test_removed_primary_is_not_replaced_by_an_outdated_file() -> None:
    now = datetime.now(timezone.utc)
    cid = await _candidate()
    await _document(
        cid,
        "glowne_cv.pdf",
        b"%PDF-1.4 usuniete " + uuid.uuid4().hex.encode(),
        source_deleted_at=now,
        removed_at=now,
    )
    await _document(
        cid,
        "cv_2024.pdf",
        b"%PDF-1.4 nieaktualne " + uuid.uuid4().hex.encode(),
        age_days=2,
        outdated_at=now,
    )

    assert await _current(cid) is None

    await _document(
        cid,
        "cv_2021.pdf",
        b"%PDF-1.4 starsze " + uuid.uuid4().hex.encode(),
        age_days=900,
    )
    current = await _current(cid)
    assert current is not None and current.filename == "cv_2021.pdf"


async def test_only_cv_named_b2b_stays_the_current_cv() -> None:
    """Bez heurystyki po nazwie: jedyne CV „…B2B…” bez flagi głównego dalej
    jest bieżącym CV (stare importy nie mają flagi)."""
    cid = await _candidate()
    await _document(cid, "Anna_B2B_Bank.docx", b"PK b2b " + uuid.uuid4().hex.encode())

    current = await _current(cid)

    assert current is not None and current.filename == "Anna_B2B_Bank.docx"


async def test_stage_upload_copy_comes_from_the_uploaded_bytes_when_storage_fails(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.cv_text_extractor.extract_text",
        lambda *_args, **_kwargs: "",
    )
    stored: dict[str, bytes] = {}

    def upload_cv(content, filename, content_type=None, *, storage_key=None):
        key = storage_key or f"cv/test/{uuid.uuid4().hex}"
        stored[key] = content
        return key

    def download_cv(storage_key: str) -> bytes:
        # Kopie CV etapu czytają się, plik kandydata — awaria magazynu.
        if storage_key.startswith("stage-cv/"):
            return stored[storage_key]
        raise RuntimeError("magazyn niedostępny")

    monkeypatch.setattr("app.services.object_storage.is_available", lambda: True)
    monkeypatch.setattr("app.services.object_storage.upload_cv", upload_cv)
    monkeypatch.setattr("app.services.object_storage.download_cv", download_cv)
    cid = await _seed_candidate_with_cv(
        cv_bytes=b"%PDF-1.4 OLD", cv_filename="stare.pdf"
    )
    stage_id = await _seed_stage(cid, await _seed_job())

    res = await app_client.post(
        f"/api/candidates/stages/{stage_id}/cv/original/upload",
        headers=app_auth_headers,
        files={"file": ("nowe-cv.pdf", NEW_PDF, "application/pdf")},
    )

    assert res.status_code == 200, res.text
    assert res.json()["original_cv_filename"] == "nowe-cv.pdf"
    copy = await _copy(stage_id)
    assert copy.original_cv_sha256 == _sha(NEW_PDF)
    download = await app_client.get(
        f"/api/candidates/stages/{stage_id}/cv/original/download",
        headers=app_auth_headers,
    )
    assert download.status_code == 200, download.text
    assert download.content == NEW_PDF
