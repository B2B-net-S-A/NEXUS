import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.api import cv_generator_b2b as api


@pytest.mark.parametrize("case", ["valid", "corrupt", "missing", "processing"])
async def test_download_uses_exact_stored_bytes_without_rerender(monkeypatch, case):
    raw = b"synthetic-original-docx"
    row = SimpleNamespace(
        id=11,
        filename="test.docx",
        candidate_name="Synthetic",
        status="processing" if case == "processing" else "ready",
        docx_content=None if case == "missing" else raw,
        docx_sha256="bad" if case == "corrupt" else hashlib.sha256(raw).hexdigest(),
    )
    monkeypatch.setattr(api, "_load_generated_document", AsyncMock(return_value=row))
    render = Mock(side_effect=AssertionError("Stored document must not be rerendered"))
    monkeypatch.setattr(api, "rerender_docx_from_payload", render)
    if case == "valid":
        response = await api.download_generated_cv(11, object(), AsyncMock())
        assert response.body == raw
    else:
        with pytest.raises(HTTPException) as error:
            await api.download_generated_cv(11, object(), AsyncMock())
        assert error.value.status_code == 409
    render.assert_not_called()
