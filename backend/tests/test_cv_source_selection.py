from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.cv_generator_b2b import standalone_service as svc


async def test_unavailable_explicit_file_never_falls_back_to_another_cv():
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
    query = db.scalars.call_args_list[1].args[0]
    compiled = query.compile()
    assert "candidate_documents.candidate_id =" in str(compiled)
    assert "candidate_documents.id =" in str(compiled)
    assert 2 in compiled.params.values()
    assert 71 in compiled.params.values()
    assert db.scalars.await_count == 2
    db.scalar.assert_not_awaited()


async def test_source_listing_exposes_only_selection_metadata():
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=2)
    db.scalars.return_value = Mock(
        all=Mock(
            return_value=[
                SimpleNamespace(
                    id=71,
                    filename="source.docx",
                    is_primary=True,
                    uploaded_at=None,
                    storage_key="private-location",
                    file_content=b"private-source",
                )
            ]
        )
    )
    rows = await svc.list_candidate_cv_sources(db, 2)
    assert rows == [
        {"id": 71, "filename": "source.docx", "is_primary": True, "uploaded_at": None}
    ]
    assert "candidate_documents.candidate_id =" in str(db.scalars.call_args.args[0])
