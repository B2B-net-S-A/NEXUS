"""Runda 9 audytu — generator CV (kod CVGEN), testy bez bazy."""

from __future__ import annotations

from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import cv_source
from app.services.cv_generator_b2b import standalone_service as svc


def _sql(query) -> str:
    return str(query.compile(compile_kwargs={"literal_binds": True}))


# ── R9-X1-1 / R9-N7-11: bieżące CV ────────────────────────────────────────


async def test_current_cv_query_loads_bytea_and_skips_non_cv_kinds():
    db = AsyncMock()
    db.scalars.return_value = Mock(first=Mock(return_value=None))
    candidate = NS(id=5, cv_storage_key=None, cv_file_content=None, cv_language=None)
    assert await cv_source.get_current_cv(db, candidate) is None
    sql = _sql(db.scalars.call_args.args[0])
    # undefer: kolumna BYTEA jest w SELECT, nie doczytywana leniwie.
    assert "candidate_documents.file_content" in sql.split("FROM")[0]
    assert "document_kind NOT IN ('certificate', 'cover_letter')" in sql
    assert "CASE WHEN (candidate_documents.document_kind = 'cv')" in sql


async def test_generation_source_query_loads_bytea_and_skips_non_cv_kinds():
    db = AsyncMock()
    db.get.return_value = NS(id=2, name="A", lastname="B")
    db.scalars.return_value = Mock(first=Mock(return_value=None))
    db.scalar.return_value = None
    with pytest.raises(svc.StandaloneGenerationError):
        await svc.load_candidate_generation_source(db, candidate_id=2, stage_id=None)
    sql = _sql(db.scalars.call_args_list[0].args[0])
    assert "candidate_documents.file_content" in sql.split("FROM")[0]
    assert "document_kind NOT IN ('certificate', 'cover_letter')" in sql


async def test_explicitly_chosen_document_is_not_filtered_by_kind():
    db = AsyncMock()
    db.get.return_value = NS(id=2, name="A", lastname="B")
    db.scalars.return_value = Mock(first=Mock(return_value=None))
    with pytest.raises(svc.StandaloneGenerationError, match="Wybrane CV"):
        await svc.load_candidate_generation_source(
            db, candidate_id=2, stage_id=None, cv_document_id=71
        )
    sql = _sql(db.scalars.call_args_list[0].args[0])
    assert "NOT IN ('certificate'" not in sql
