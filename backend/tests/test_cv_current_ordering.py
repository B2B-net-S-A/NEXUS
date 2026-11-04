"""Wybór bieżącego CV nie zależy od układu wierszy w bazie (04.11.2026).

Pliki z importu Traffita mają NULL w `uploaded_at`, a Postgres przy DESC stawia
NULL pierwszy. Na kopii produkcji u 28 osób plik bez daty wygrywał z plikiem
z datą, a 34 osoby miały co najmniej 2 pliki bez daty w najlepszej randze, gdzie
sam UPDATE innej kolumny zmieniał plik w paczce CV.

Kontrakty:

- w tej samej randze plik z datą wygrywa z plikiem bez daty;
- przy tej samej dacie albo jej braku wygrywa najwyższe id;
- ranga jest ważniejsza od daty: główny plik bez daty i rodzaj „cv” bez daty
  nie ustępują nowszemu plikowi o gorszej randze.

Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Optional

from sqlalchemy.dialects import postgresql

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.services.cv_generator_b2b.standalone_service import (
    list_candidate_cv_sources,
    load_candidate_generation_source,
)
from app.services.cv_qc import _newer_profile_cv
from app.services.cv_source import current_cv_ordering, get_current_cv

NOW = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
_CV = CandidateDocumentKind.cv
_OTHER = CandidateDocumentKind.other


async def _person(
    *rows: tuple[str, Optional[datetime], CandidateDocumentKind, bool],
) -> tuple[int, dict[str, int]]:
    """Pliki powstają kolejno, więc pierwszy ma najniższe id i pierwszy wiersz."""
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Ewa", lastname=f"Fikcyjna-{uuid.uuid4().hex[:8]}")
        db.add(candidate)
        await db.flush()
        ids: dict[str, int] = {}
        for filename, uploaded_at, kind, primary in rows:
            doc = CandidateDocument(
                candidate_id=candidate.id,
                filename=filename,
                file_content=filename.encode(),
                document_kind=kind,
                is_primary=primary,
                uploaded_at=uploaded_at,
            )
            db.add(doc)
            await db.flush()
            ids[filename] = doc.id
        await db.commit()
        return candidate.id, ids


async def _picks(candidate_id: int) -> set[str]:
    """Plik domyślny paczki CV i kopii etapu, generatora i listy w karcie."""
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        current = await get_current_cv(db, candidate)
        source = await load_candidate_generation_source(
            db, candidate_id=candidate_id, stage_id=None, cv_document_id=None
        )
        listed = await list_candidate_cv_sources(db, candidate_id)
    return {current.filename, source.cv_filename, listed[0]["filename"]}


def test_ordering_puts_missing_dates_last_and_ends_with_id() -> None:
    """`m365_unreadable_name_rematch` i QC biorą kolejność wprost z tej funkcji."""
    clauses = [
        str(
            clause.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for clause in current_cv_ordering()
    ]
    assert clauses[-2:] == [
        "candidate_documents.uploaded_at DESC NULLS LAST",
        "candidate_documents.id DESC",
    ]


async def test_dated_file_beats_undated_import_inserted_later() -> None:
    candidate_id, _ = await _person(
        ("wgrane.pdf", NOW - timedelta(days=30), _CV, False),
        ("import.pdf", None, _CV, False),
    )
    assert await _picks(candidate_id) == {"wgrane.pdf"}


async def test_dated_file_beats_undated_import_inserted_earlier() -> None:
    candidate_id, _ = await _person(
        ("import.pdf", None, _CV, False),
        ("wgrane.pdf", NOW - timedelta(days=30), _CV, False),
    )
    assert await _picks(candidate_id) == {"wgrane.pdf"}


async def test_highest_id_wins_between_undated_files() -> None:
    candidate_id, _ = await _person(
        ("pierwszy.pdf", None, _CV, False),
        ("drugi.pdf", None, _CV, False),
        ("trzeci.pdf", None, _CV, False),
    )
    assert await _picks(candidate_id) == {"trzeci.pdf"}


async def test_highest_id_wins_between_files_with_the_same_date() -> None:
    candidate_id, _ = await _person(
        ("pierwszy.pdf", NOW, _CV, False),
        ("drugi.pdf", NOW, _CV, False),
    )
    assert await _picks(candidate_id) == {"drugi.pdf"}


async def test_undated_primary_keeps_beating_a_dated_file() -> None:
    candidate_id, _ = await _person(
        ("glowny.pdf", None, _CV, True),
        ("nowszy.pdf", NOW, _CV, False),
    )
    assert await _picks(candidate_id) == {"glowny.pdf"}


async def test_undated_cv_keeps_beating_a_dated_other_file() -> None:
    candidate_id, _ = await _person(
        ("cv.pdf", None, _CV, False),
        ("skan.pdf", NOW, _OTHER, False),
    )
    assert await _picks(candidate_id) == {"cv.pdf"}


async def test_qc_does_not_call_an_undated_import_a_newer_cv() -> None:
    """Data wiersza z importu to data importu, a nie wgrania nowszego CV."""
    candidate_id, _ = await _person(
        ("wgrane.pdf", NOW - timedelta(days=30), _CV, False),
        ("import.pdf", None, _CV, False),
    )
    sources = SimpleNamespace(
        candidate=SimpleNamespace(id=candidate_id),
        original={"source": "snapshot", "snapshot_at": NOW - timedelta(days=10)},
    )
    async with AsyncSessionLocal() as db:
        assert await _newer_profile_cv(db, sources) is None
