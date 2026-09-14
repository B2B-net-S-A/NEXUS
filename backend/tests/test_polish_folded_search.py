"""Wyszukiwanie bez wrażliwości na polskie znaki (UAT M02-B03, M06-B03, M08-B01).

Produkcja nie ma rozszerzenia ``unaccent`` — fold robi ``translate()``. Testy
chodzą po prawdziwym Postgresie, bo cała wartość tej poprawki siedzi w SQL-u.
"""

from __future__ import annotations

import unicodedata
import uuid

import pytest
from sqlalchemy import delete, literal, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.schemas.candidate_search import CandidateSearchRequest
from app.services.polish_ilike import fold_polish_query, polish_folded_ilike
from app.services.structured_candidate_search import build_structured_filter

pytestmark = [pytest.mark.integration]


def test_fold_keeps_case_and_normalises_nfd() -> None:
    assert fold_polish_query("Kraków ŁÓDŹ") == "Krakow LODZ"
    # NFD (litera + znak łączący) też jest foldowane — najpierw NFC.
    assert fold_polish_query(unicodedata.normalize("NFD", "Kraków")) == "Krakow"


@pytest.mark.parametrize(
    ("stored", "phrase", "expected"),
    [
        ("Kraków", "Krakow", True),
        ("Kraków", "krakow", True),
        ("KRAKÓW", "kraków", True),
        ("Krakow", "Kraków", True),
        ("Spółka Akcyjna", "spolka", True),
        ("Gdańsk", "Krakow", False),
        # `%` i `_` wpisane w wyszukiwarkę szukają znaku, nie są wildcardem.
        ("Kraków", "%", False),
        ("Kraków", "_", False),
    ],
)
async def test_polish_folded_ilike_on_postgres(
    stored: str, phrase: str, expected: bool
) -> None:
    async with AsyncSessionLocal() as db:
        matched = await db.scalar(select(polish_folded_ilike(literal(stored), phrase)))
    assert matched is expected


async def test_city_filter_without_diacritics_finds_city_with_them() -> None:
    """UAT M02-B03: filtr „Miasto” = „Krakow” znajduje kandydata z „Kraków”."""
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        in_krakow = Candidate(name="Test", lastname=f"Miasto{tag}", city="Kraków")
        in_blob = Candidate(
            name="Test",
            lastname=f"Blob{tag}",
            location='{"locality":"Kraków","country":"Polska"}',
        )
        elsewhere = Candidate(name="Test", lastname=f"Inne{tag}", city="Gdańsk")
        db.add_all((in_krakow, in_blob, elsewhere))
        await db.commit()
        ids = {in_krakow.id, in_blob.id, elsewhere.id}

    try:
        for phrase in ("Krakow", "krakow", "Kraków"):
            request = CandidateSearchRequest(location_cities=[phrase])
            async with AsyncSessionLocal() as db:
                found = set(
                    (
                        await db.execute(
                            select(Candidate.id).where(
                                Candidate.id.in_(ids),
                                *build_structured_filter(request),
                            )
                        )
                    ).scalars()
                )
            assert found == {in_krakow.id, in_blob.id}, phrase
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
            await db.commit()
