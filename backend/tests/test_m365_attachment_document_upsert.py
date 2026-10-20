"""Dokument z m365 szukany po tym samym kluczu, na ktorym stoi UNIQUE.

3 800 zdarzen w Sentry w 14 dni (NEXUS-BE-2Y i 2X) mialo jedna przyczyne:
lookup dokumentu szukal po `(candidate_id, content_sha256, source_deleted_at
IS NULL)`, a indeks `ux_candidate_documents_external_source_id` (migracja 0076)
stoi na `(external_source, external_id) WHERE external_id IS NOT NULL`. Zaden
z trzech warunkow lookupu nie wystepuje w indeksie, wiec istnialy dwie drogi
do kolizji, ktorych lookup nie widzial:

1. dokument MIEKKO USUNIETY - wypada z lookupu (`source_deleted_at IS NULL`),
   ale nadal zajmuje klucz w indeksie. Kazda kolejna synchronizacja tego
   zalacznika probowala INSERT-a i TRWALE padala;
2. ten sam zalacznik dopasowany do INNEGO kandydata - lookup filtruje po
   `candidate_id`, indeks jest globalny.

Bez savepointu `IntegrityError` zatruwal CALA sesje, wiec padal nie ten jeden
zalacznik, tylko caly dalszy przebieg synchronizacji - stad `PendingRollbackError`
jako najczestszy blad w calym NEXUS-ie.
"""

import ast
import hashlib
import pathlib
import uuid

import pytest
from sqlalchemy import select, text

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _handler_source() -> str:
    return (BACKEND / "app/services/m365/attachment_handler.py").read_text(
        encoding="utf-8"
    )


def test_lookup_uses_the_key_the_unique_index_uses():
    """PIERWSZY lookup musi pytac o klucz indeksu, nie o hash tresci.

    Ten test byl najpierw napisany jako `"external_id" in src` i NIE zlapal
    sabotazu: po zepsuciu pierwszego lookupu drugie wystapienie tego napisu
    (re-SELECT po IntegrityError) zostawalo, wiec asercja przechodzila.
    "Czy napis gdziekolwiek jest" nie mowi nic o tym, KTORY lookup decyduje -
    dlatego pytamy AST o pierwsze zapytanie w kolejnosci zrodlowej.
    """
    tree = ast.parse(_handler_source())
    queries: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "attr", None) != "scalar" or not node.args:
            continue
        dumped = ast.dump(node.args[0])
        if "CandidateDocument" not in dumped:
            continue
        queries.append((node.lineno, dumped))

    assert queries, "nie znaleziono zapytania o CandidateDocument"
    queries.sort()
    first = queries[0][1]
    assert "external_id" in first, (
        "PIERWSZY lookup nie pyta o external_id - to dokladnie defekt, ktory "
        "dal 3 800 zdarzen: szukamy po innym kluczu niz ten, na ktorym stoi "
        "UNIQUE, wiec miekko usuniety wiersz jest niewidoczny"
    )
    assert "external_source" in first


def test_insert_is_wrapped_in_a_savepoint():
    """Bez savepointu kolizja zatruwa sesje i ubija caly przebieg."""
    src = _handler_source()
    tree = ast.parse(src)
    nested = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncWith)
        and any(
            isinstance(i.context_expr, ast.Call)
            and getattr(i.context_expr.func, "attr", None) == "begin_nested"
            for i in n.items
        )
    ]
    assert nested, (
        "brak `async with db.begin_nested()` wokol INSERT-u dokumentu - "
        "IntegrityError zatruje sesje, tak jak przed naprawa"
    )
    assert "except IntegrityError" in src, (
        "savepoint bez lapania IntegrityError nic nie daje"
    )


@pytest.mark.asyncio
async def test_soft_deleted_document_does_not_block_reinsert():
    """Miekko usuniety dokument m365 musi byc WSKRZESZONY, nie duplikowany.

    To droga nr 1 z docstringu modulu, odtworzona na prawdziwej bazie:
    wiersz z ustawionym `source_deleted_at` jest niewidoczny dla starego
    lookupu, ale nadal zajmuje klucz w indeksie UNIQUE.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument

    ext_id = f"m365-test-{uuid.uuid4().hex[:16]}"
    content = b"PDF-ish bytes"
    digest = hashlib.sha256(content).hexdigest()

    async with AsyncSessionLocal() as db:
        cand = Candidate(name="Test", lastname=f"M365-{uuid.uuid4().hex[:6]}")
        db.add(cand)
        await db.flush()
        cand_id = cand.id

        doc = CandidateDocument(
            candidate_id=cand_id,
            filename="cv.pdf",
            file_content=content,
            content_type="application/pdf",
            size_bytes=len(content),
            external_source="m365",
            external_id=ext_id,
            content_sha256=digest,
        )
        db.add(doc)
        await db.flush()
        # miekkie usuniecie - wiersz wypada z lookupu, zostaje w indeksie
        await db.execute(
            text(
                "UPDATE candidate_documents SET source_deleted_at = now() WHERE id = :i"
            ),
            {"i": doc.id},
        )
        await db.commit()
        doc_id = doc.id

    # Powtorny INSERT z tym samym external_id MUSI paść na UNIQUE - to dowod,
    # ze indeks nie filtruje `source_deleted_at`, czyli ze stary lookup byl
    # strukturalnie niewystarczajacy.
    from sqlalchemy.exc import IntegrityError

    async with AsyncSessionLocal() as db:
        dup = CandidateDocument(
            candidate_id=cand_id,
            filename="cv.pdf",
            file_content=content,
            content_type="application/pdf",
            size_bytes=len(content),
            external_source="m365",
            external_id=ext_id,
            content_sha256=digest,
        )
        db.add(dup)
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()

    # A lookup po kluczu indeksu ten wiersz WIDZI - czyli naprawiony handler
    # przejdzie na update zamiast na INSERT.
    async with AsyncSessionLocal() as db:
        found = await db.scalar(
            select(CandidateDocument).where(
                CandidateDocument.external_source == "m365",
                CandidateDocument.external_id == ext_id,
            )
        )
        assert found is not None and found.id == doc_id, (
            "lookup po kluczu indeksu nie widzi miekko usunietego wiersza - "
            "naprawa nie dziala"
        )
        await db.execute(
            text("DELETE FROM candidate_documents WHERE id = :i"), {"i": doc_id}
        )
        await db.execute(text("DELETE FROM candidates WHERE id = :i"), {"i": cand_id})
        await db.commit()


# 20.10.2026: identyfikator załącznika M365 ma 176–180 znaków, a kolumna
# `candidate_documents.external_id` 100. Ucinanie do 100 znaków zostawiało
# wspólny początek skrzynki — na produkcji 3 964 załączniki dawały 13 kluczy.
# CV z nowego maila „znajdowało” cudzy dokument i przepinało go na swojego
# kandydata razem z cudzym plikiem (kandydat 6673 dostał CV kandydata 26224).

_SHARED_PREFIX = "AAMkSyntheticMailboxPrefix" + "x" * 94


def test_document_key_keeps_attachments_with_a_shared_prefix_apart():
    from app.services.m365.attachment_handler import m365_document_external_id

    first = m365_document_external_id(_SHARED_PREFIX + "AAABEgAQAOne")
    second = m365_document_external_id(_SHARED_PREFIX + "AAABEgAQATwo")

    assert first != second
    assert first == m365_document_external_id(_SHARED_PREFIX + "AAABEgAQAOne")
    assert len(first) <= 100 and len(second) <= 100
    assert first != (_SHARED_PREFIX + "AAABEgAQAOne")[:100]


def test_document_key_is_empty_without_an_attachment_id():
    from app.services.m365.attachment_handler import m365_document_external_id

    assert m365_document_external_id(None) is None
    assert m365_document_external_id("") is None


@pytest.mark.asyncio
async def test_cv_from_another_mail_does_not_take_over_a_document(
    monkeypatch, tmp_path
):
    """Dwa różne załączniki o wspólnym początku id → dwa dokumenty."""
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument
    from app.services import (
        candidate_identity_quarantine,
        cv_ingest_service,
        cv_parser,
        cv_text_extractor,
    )
    from app.services.m365 import attachment_handler

    now = datetime.now(timezone.utc)
    prefix = _SHARED_PREFIX[:-12] + uuid.uuid4().hex[:12]
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
        first_person = Candidate(name="Alex", lastname="Example")
        second_person = Candidate(name="Sam", lastname="Example")
        db.add_all([first_person, second_person])
        await db.flush()

        documents = {}
        for index, (person, content) in enumerate(
            [
                (first_person, b"First synthetic CV"),
                (second_person, b"Second synthetic CV"),
            ]
        ):
            filename = f"synthetic-{index}.pdf"
            (tmp_path / filename).write_bytes(content)
            attachment = SimpleNamespace(
                id=index + 1,
                is_cv_candidate=True,
                storage_path=filename,
                filename=filename,
                content_type="application/pdf",
                sha256=None,
                m365_attachment_id=f"{prefix}ATTACHMENT{index}",
                parsed_candidate_id=None,
                parse_error=None,
            )
            email = SimpleNamespace(
                candidate_id=person.id, received_at=now - timedelta(days=1)
            )
            await attachment_handler.try_parse_cv(db, attachment, email)
            await db.flush()
            documents[person.id] = list(
                await db.scalars(
                    select(CandidateDocument).where(
                        CandidateDocument.candidate_id == person.id,
                        CandidateDocument.external_source == "m365",
                    )
                )
            )

        assert [d.file_content for d in documents[first_person.id]] == [
            b"First synthetic CV"
        ]
        assert [d.file_content for d in documents[second_person.id]] == [
            b"Second synthetic CV"
        ]
        # Wszystko syntetyczne i niezatwierdzone: zamknięcie sesji to cofa.
