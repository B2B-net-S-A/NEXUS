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
