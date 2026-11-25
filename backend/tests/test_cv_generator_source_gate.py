"""Lista plików generatora i jawny wybór pliku idą przez bramkę bieżącego CV.

25.11.2026, decyzja Artura („filtr wszędzie”): automat CV bierze pierwszy plik
z `list_candidate_cv_sources`, a front zaznacza go domyślnie i wysyła jako jawne
`cv_document_id`. Obie drogi pomijały `current_cv_filters_for`, więc na kopii
produkcji 3 ręczne CV z 60 dni powstały z pliku w kwarantannie tożsamości (CV innej
osoby), a u 136 osób pierwszy plik listy był w kwarantannie. Dane fikcyjne.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.dialects import postgresql

from app.services import cv_source
from app.services.cv_generator_b2b import standalone_service as svc


def _sql(query) -> str:
    return str(query.compile(dialect=postgresql.dialect()))


@pytest.fixture(autouse=True)
def _no_quarantined_copies(monkeypatch):
    async def none(_db, _candidate_id):
        return frozenset()

    monkeypatch.setattr(cv_source, "quarantined_copy_document_ids", none)


async def test_listing_hides_outdated_and_quarantined_files():
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=2)
    db.scalars.return_value = Mock(all=Mock(return_value=[]))

    await svc.list_candidate_cv_sources(db, 2)

    sql = _sql(db.scalars.call_args.args[0])
    assert "candidate_documents.outdated_at IS NULL" in sql
    assert "candidate_source_identity_reviews" in sql


async def test_listing_hides_copies_of_a_quarantined_file(monkeypatch):
    async def copies(_db, _candidate_id):
        return frozenset({71})

    monkeypatch.setattr(cv_source, "quarantined_copy_document_ids", copies)
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=2)
    db.scalars.return_value = Mock(all=Mock(return_value=[]))

    await svc.list_candidate_cv_sources(db, 2)

    compiled = db.scalars.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "candidate_documents.id NOT IN" in str(compiled)
    assert [71] in compiled.params.values()


async def test_explicit_file_goes_through_the_same_gate():
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=2)
    stage = SimpleNamespace(candidate_id=2, job=SimpleNamespace(client_id=None))
    db.scalars.side_effect = [
        Mock(first=Mock(return_value=stage)),
        Mock(first=Mock(return_value=None)),
    ]

    with pytest.raises(svc.StandaloneGenerationError, match="Wybrane CV"):
        await svc.load_candidate_generation_source(
            db, candidate_id=2, stage_id=3, cv_document_id=71
        )

    sql = _sql(db.scalars.call_args_list[1].args[0])
    assert "candidate_documents.id =" in sql
    assert "candidate_documents.outdated_at IS NULL" in sql
    assert "candidate_source_identity_reviews" in sql
