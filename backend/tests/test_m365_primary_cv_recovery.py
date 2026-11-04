"""Restoring a source must not promote it before the identity gate flushes."""

from datetime import datetime, timedelta, timezone
import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.services import candidate_identity_quarantine, cv_ingest_service, cv_parser
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
    # Od 17.09.2026 załącznik z maila przechodzi przez wspólną ścieżkę po
    # odczycie CV (`cv_ingest_service.finish_cv_ingest`), nie przez gołe
    # `_apply_cv_enrichment`.
    enrichment = AsyncMock()
    monkeypatch.setattr(cv_ingest_service, "finish_cv_ingest", enrichment)

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
            external_id=attachment_handler.m365_document_external_id(ext_id),
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
            enrichment.assert_awaited_once()
        # Everything is synthetic and left uncommitted: close rolls it back.


@pytest.mark.asyncio
@pytest.mark.parametrize("same_person", [True, False])
async def test_file_removed_from_profile_is_not_restored_for_the_same_person(
    monkeypatch, tmp_path, same_person
):
    """0435: „Usuń z profilu” przeżywa powrót załącznika w synchronizacji.

    U tej samej osoby plik zostaje usunięty; załącznik przypisany innej osobie
    (rematch) trafia do niej normalnie i przestaje być „usunięty”.
    """
    now = datetime.now(timezone.utc)
    ext_id = f"m365-removed-{uuid.uuid4().hex}"
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
    monkeypatch.setattr(cv_ingest_service, "finish_cv_ingest", AsyncMock())
    monkeypatch.setattr(
        candidate_identity_quarantine,
        "record_detected_identity",
        AsyncMock(return_value=SimpleNamespace(is_quarantined=False)),
    )

    async with AsyncSessionLocal() as db:
        owner = Candidate(name="Alex", lastname="Example")
        other = Candidate(name="Other", lastname="Example")
        db.add_all([owner, other])
        await db.flush()
        removed = CandidateDocument(
            candidate_id=owner.id,
            filename="synthetic.pdf",
            file_content=content,
            content_type="application/pdf",
            size_bytes=len(content),
            document_kind=CandidateDocumentKind.cv,
            is_primary=False,
            source_deleted_at=now,
            removed_at=now,
            external_source="m365",
            external_id=attachment_handler.m365_document_external_id(ext_id),
        )
        db.add(removed)
        await db.flush()

        target = owner if same_person else other
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
            candidate_id=target.id, received_at=now - timedelta(days=1)
        )
        await attachment_handler.try_parse_cv(db, attachment, email)
        await db.flush()
        await db.refresh(removed)

        assert attachment.parsed_candidate_id == target.id
        if same_person:
            assert removed.source_deleted_at is not None
            assert removed.removed_at is not None
            assert removed.is_primary is False
            assert owner.raw_cv_text is None
        else:
            assert removed.candidate_id == other.id
            assert removed.source_deleted_at is None
            assert removed.removed_at is None
        # Dane syntetyczne, bez commitu: zamknięcie sesji je wycofuje.


@pytest.mark.asyncio
@pytest.mark.parametrize("same_attachment", [True, False])
async def test_file_removed_under_the_old_key_is_not_restored(
    monkeypatch, tmp_path, same_attachment
):
    """0435 także dla dokumentu ze starym kluczem (`id[:100]`, sprzed #2447).

    Nowy klucz (skrót całego id) takiego dokumentu nie znajduje, a zapasowe
    szukanie po treści pomijało usunięte — wstawiał się nowy dokument i plik
    usunięty z profilu wracał (audyt 21.10.2026, kandydat po naprawie poczty).
    Ten sam plik w NOWYM mailu to dalej nowy dokument, jak ponowne wgranie.
    """
    now = datetime.now(timezone.utc)
    ext_id = f"m365-old-key-{uuid.uuid4().hex}" + "x" * 120
    content = b"Synthetic old key CV " + uuid.uuid4().hex.encode()
    sha = hashlib.sha256(content).hexdigest()
    (tmp_path / "synthetic.pdf").write_bytes(content)
    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(attachment_handler.settings, "M365_AUTO_PARSE_CV", True)
    monkeypatch.setattr(cv_text_extractor, "extract_text", lambda *_: "Synthetic CV")
    monkeypatch.setattr(
        cv_parser,
        "parse_cv",
        AsyncMock(return_value={"first_name": "Alex", "last_name": "Example"}),
    )
    monkeypatch.setattr(cv_ingest_service, "finish_cv_ingest", AsyncMock())
    monkeypatch.setattr(
        candidate_identity_quarantine,
        "record_detected_identity",
        AsyncMock(return_value=SimpleNamespace(is_quarantined=False)),
    )

    async with AsyncSessionLocal() as db:
        owner = Candidate(name="Alex", lastname="Example")
        db.add(owner)
        await db.flush()
        removed = CandidateDocument(
            candidate_id=owner.id,
            filename="synthetic.pdf",
            file_content=content,
            content_type="application/pdf",
            size_bytes=len(content),
            document_kind=CandidateDocumentKind.cv,
            is_primary=False,
            source_deleted_at=now,
            removed_at=now,
            external_source="m365",
            external_id=ext_id[:100],
            content_sha256=sha,
        )
        db.add(removed)
        await db.flush()

        attachment = SimpleNamespace(
            id=1,
            is_cv_candidate=True,
            storage_path="synthetic.pdf",
            filename="synthetic.pdf",
            content_type="application/pdf",
            sha256=sha,
            m365_attachment_id=(
                ext_id
                if same_attachment
                else f"m365-new-mail-{uuid.uuid4().hex}" + "x" * 120
            ),
            parsed_candidate_id=None,
            parse_error=None,
        )
        email = SimpleNamespace(
            candidate_id=owner.id, received_at=now - timedelta(days=1)
        )
        await attachment_handler.try_parse_cv(db, attachment, email)
        await db.flush()
        await db.refresh(removed)

        assert attachment.parsed_candidate_id == owner.id
        assert removed.removed_at is not None
        assert removed.source_deleted_at is not None
        docs = list(
            await db.scalars(
                select(CandidateDocument.id).where(
                    CandidateDocument.candidate_id == owner.id
                )
            )
        )
        if same_attachment:
            assert docs == [removed.id]
            assert owner.raw_cv_text is None
        else:
            assert len(docs) == 2 and removed.id in docs
        # Dane syntetyczne, bez commitu: zamknięcie sesji je wycofuje.


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


@pytest.mark.asyncio
async def test_unreadable_candidate_name_keeps_mail_cv_out_of_primary(
    monkeypatch, tmp_path
):
    """Imię cyrylicą: bramka daje `inconclusive`, więc CV z maila nie zostaje
    głównym i nie nadpisuje profilu (20.10.2026 — cudze CV jako główne)."""
    now = datetime.now(timezone.utc)
    ext_id = f"m365-unreadable-{uuid.uuid4().hex}"
    content = b"Synthetic foreign CV"
    (tmp_path / "foreign.pdf").write_bytes(content)
    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(attachment_handler.settings, "M365_AUTO_PARSE_CV", True)
    monkeypatch.setattr(cv_text_extractor, "extract_text", lambda *_: "Foreign CV")
    monkeypatch.setattr(
        cv_parser,
        "parse_cv",
        AsyncMock(return_value={"first_name": "Alex", "last_name": "Example"}),
    )
    enrichment = AsyncMock()
    monkeypatch.setattr(cv_ingest_service, "finish_cv_ingest", enrichment)

    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Іван", lastname="Петренко", raw_cv_text="Existing trusted CV"
        )
        db.add(candidate)
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
        db.add(current)
        await db.flush()
        attachment = SimpleNamespace(
            id=1,
            is_cv_candidate=True,
            storage_path="foreign.pdf",
            filename="foreign.pdf",
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
        added = await db.scalar(
            select(CandidateDocument).where(
                CandidateDocument.external_source == "m365",
                CandidateDocument.external_id
                == attachment_handler.m365_document_external_id(ext_id),
            )
        )

        assert added is not None and added.candidate_id == candidate.id
        assert added.is_primary is False
        assert current.is_primary is True
        assert candidate.raw_cv_text == "Existing trusted CV"
        assert attachment.parsed_candidate_id == candidate.id
        assert attachment.parse_error == "identity_unreadable_not_primary"
        enrichment.assert_not_called()
        # Dane syntetyczne, bez commitu: zamknięcie sesji je wycofuje.


class _NoopSavepoint:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _SessionWithoutDocuments:
    """Atrapa sesji: profil bez dokumentów m365, nowy dokument dostaje id."""

    def __init__(self, candidate) -> None:
        self.candidate = candidate
        self.added: list = []
        self.execute = AsyncMock()

    async def scalar(self, *_a, **_kw):
        return None

    async def get(self, _model, _id):
        return self.candidate

    def add(self, obj) -> None:
        self.added.append(obj)

    def begin_nested(self) -> _NoopSavepoint:
        return _NoopSavepoint()

    async def flush(self) -> None:
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 501


@pytest.mark.asyncio
@pytest.mark.parametrize("identity_proven", [True, False])
async def test_unreadable_name_cv_is_read_when_identity_comes_from_the_cv(
    monkeypatch, tmp_path, identity_proven
):
    """Audyt 22.10.2026 (F68, decyzja Artura): kandydat założony z tego CV
    (albo dopasowany po e-mailu z CV) ma pewną tożsamość — imię cyrylicą nie
    odcina wtedy CV od profilu. Mail dopasowany po wątku dalej nie zasila."""
    (tmp_path / "olena.pdf").write_bytes(b"Synthetic Olena CV")
    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(attachment_handler.settings, "M365_AUTO_PARSE_CV", True)
    monkeypatch.setattr(
        candidate_identity_quarantine,
        "record_detected_identity",
        AsyncMock(return_value=SimpleNamespace(is_quarantined=False)),
    )
    enrichment = AsyncMock()
    monkeypatch.setattr(cv_ingest_service, "finish_cv_ingest", enrichment)
    candidate = SimpleNamespace(
        id=31,
        name="Олена",
        lastname="Петренко",
        cv_parsed_at=None,
        raw_cv_text=None,
        cv_filename=None,
    )
    attachment = SimpleNamespace(
        id=1,
        is_cv_candidate=True,
        storage_path="olena.pdf",
        filename="olena.pdf",
        content_type="application/pdf",
        sha256=None,
        m365_attachment_id=f"m365-olena-{uuid.uuid4().hex}",
        parsed_candidate_id=None,
        parse_error=None,
        cv_parse_attempted_at=None,
    )
    email = SimpleNamespace(candidate_id=None, received_at=None)
    db = _SessionWithoutDocuments(candidate)

    await attachment_handler.try_parse_cv(
        db,
        attachment,
        email,
        preparsed=("Олена Петренко CV", {"first_name": "Олена"}),
        candidate_id=candidate.id,
        identity_proven=identity_proven,
    )

    (document,) = db.added
    assert attachment.parsed_candidate_id == candidate.id
    if identity_proven:
        assert document.is_primary is True
        assert attachment.parse_error is None
        assert candidate.raw_cv_text == "Олена Петренко CV"
        enrichment.assert_awaited_once()
    else:
        assert document.is_primary is False
        assert attachment.parse_error == "identity_unreadable_not_primary"
        assert candidate.raw_cv_text is None
        enrichment.assert_not_called()
