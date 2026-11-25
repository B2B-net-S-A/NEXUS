"""Umowa i NDA nie są źródłem CV w generatorze (decyzja Artura 25.11.2026).

Pomiar na kopii produkcji 25.11.2026: przez 60 dni 3 z 1727 CV z generatora
powstały z umowy przedwstępnej albo NDA (skan bez tekstu), bo generator bierze
każdy PDF/DOCX z profilu, a import Traffita oznaczył takie pliki jako „CV”,
często jako główne. 148 osób ma dziś umowę albo NDA jako pierwszy plik do CV.

Kontrakty:

- plik z umową albo NDA w nazwie (bez CV w nazwie) nie trafia na listę plików
  generatora i nie jest wybierany domyślnie, także jako główne CV;
- osoba z samą umową nie ma pliku do generacji (automat pomija „brak pliku CV”),
  a komunikat mówi, że w profilu jest umowa, nie CV;
- wskazanie umowy wprost kończy się komunikatem, nie CV z umowy;
- nazwiska i słowa z „umow” w środku (Gumowski, podsumowanie) oraz „contractor”
  zostają CV.

Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    list_candidate_cv_sources,
    load_candidate_generation_source,
)
from app.services.cv_source import looks_like_contract_file

NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)
CONTRACT = "Umowa przedwstepna_2024_Ewa Fikcyjna-podpisany.pdf"
NDA = "NDA_Ewa Fikcyjna.pdf"
OWN = "Ewa_Fikcyjna_CV.pdf"


@pytest.mark.parametrize(
    "filename",
    [
        CONTRACT,
        NDA,
        "umowa_ramowa.docx",
        "Umów_zestawienie.pdf",
        "nda.pdf",
        "Non-Disclosure Agreement signed.pdf",
        "B2B agreement.docx",
        "Service contract 2025.pdf",
    ],
)
def test_contract_names_are_not_cv(filename: str) -> None:
    assert looks_like_contract_file(filename)


@pytest.mark.parametrize(
    "filename",
    [
        OWN,
        "Jan Gumowski.pdf",
        "jan_szumowski_resume.pdf",
        "podsumowanie_kariery.pdf",
        "Cloud_B2B_contractor.pdf",
        "Contract Manager - Jan Fikcyjny.pdf",
        "CV_umowa_o_dzielo_doswiadczenie.pdf",
        "Agenda.pdf",
    ],
)
def test_cv_names_stay_cv(filename: str) -> None:
    assert not looks_like_contract_file(filename)


def _doc(
    candidate_id: int,
    filename: str,
    *,
    primary: bool = False,
    age_days: int = 0,
) -> CandidateDocument:
    return CandidateDocument(
        candidate_id=candidate_id,
        filename=filename,
        file_content=filename.encode(),
        document_kind=CandidateDocumentKind.cv,
        is_primary=primary,
        uploaded_at=NOW - timedelta(days=age_days),
    )


async def _person(*rows: tuple[str, dict]) -> tuple[int, dict[str, int]]:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Ewa", lastname=f"Fikcyjna-{uuid.uuid4().hex[:8]}")
        db.add(candidate)
        await db.flush()
        docs = [_doc(candidate.id, name, **options) for name, options in rows]
        db.add_all(docs)
        await db.flush()
        ids = {doc.filename: doc.id for doc in docs}
        await db.commit()
        return candidate.id, ids


async def _generator_file(candidate_id: int, document_id: Optional[int] = None) -> str:
    async with AsyncSessionLocal() as db:
        source = await load_candidate_generation_source(
            db, candidate_id=candidate_id, stage_id=None, cv_document_id=document_id
        )
    return source.cv_filename


async def _source_names(candidate_id: int) -> list[str]:
    async with AsyncSessionLocal() as db:
        return [
            row["filename"] for row in await list_candidate_cv_sources(db, candidate_id)
        ]


async def test_primary_contract_gives_way_to_the_candidate_cv() -> None:
    candidate_id, _ = await _person(
        (CONTRACT, {"primary": True}),
        (OWN, {"age_days": 400}),
    )
    assert await _source_names(candidate_id) == [OWN]
    assert await _generator_file(candidate_id) == OWN


async def test_newer_nda_is_not_a_source() -> None:
    candidate_id, _ = await _person(
        (NDA, {}),
        (OWN, {"age_days": 30}),
    )
    assert await _source_names(candidate_id) == [OWN]
    assert await _generator_file(candidate_id) == OWN


async def test_person_with_only_a_contract_has_no_cv_to_generate_from() -> None:
    candidate_id, _ = await _person((CONTRACT, {"primary": True}), (NDA, {}))
    assert await _source_names(candidate_id) == []
    with pytest.raises(StandaloneGenerationError) as err:
        await _generator_file(candidate_id)
    assert err.value.code == "no_cv_file"
    assert "umow" in err.value.message.lower()


async def test_contract_picked_directly_is_refused() -> None:
    candidate_id, ids = await _person((NDA, {}), (OWN, {"age_days": 30}))
    with pytest.raises(StandaloneGenerationError) as err:
        await _generator_file(candidate_id, ids[NDA])
    assert err.value.code == "no_cv_file"
    assert "umow" in err.value.message.lower()
