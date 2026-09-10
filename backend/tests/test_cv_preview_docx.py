"""Preview download returns the stored artifact, never another model/render call."""

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api import client_cv_rules as api


@pytest.mark.parametrize("variant", ["with_rule", "without_rule"])
@pytest.mark.parametrize("case", ["ready", "corrupt", "foreign", "missing", "denied"])
async def test_preview_docx_integrity_and_client_scope(monkeypatch, variant, case):
    content = b"exact-generated-docx-artifact"
    metadata = {
        "filename": "Zażółć.docx",
        "docx_sha256": hashlib.sha256(content).hexdigest(),
    }
    row = SimpleNamespace(
        client_id=99 if case == "foreign" else 5,
        status="ready",
        with_rule=metadata,
        without_rule=metadata,
        with_rule_docx=content,
        without_rule_docx=content,
    )
    if case == "corrupt":
        setattr(row, variant + "_docx", b"changed")
    if case == "missing":
        setattr(row, variant + "_docx", None)
    db = AsyncMock()
    db.get.return_value = row
    monkeypatch.setattr(api, "_client_or_404", AsyncMock())
    guard = AsyncMock(side_effect=HTTPException(403) if case == "denied" else None)
    monkeypatch.setattr(api, "_require_client_rule_access", guard)
    if case != "ready":
        with pytest.raises(HTTPException) as error:
            await api.download_rule_preview_docx(
                5, 12, variant, SimpleNamespace(id=7), db
            )
        assert (
            error.value.status_code
            == {"corrupt": 409, "missing": 409, "foreign": 404, "denied": 403}[case]
        )
        if case == "denied":
            db.get.assert_not_awaited()
    else:
        response = await api.download_rule_preview_docx(
            5, 12, variant, SimpleNamespace(id=7), db
        )
        assert response.body == content
        assert response.headers["x-content-sha256"] == metadata["docx_sha256"]
        assert response.headers["cache-control"] == "no-store"
        assert "filename*=UTF-8''" in response.headers["content-disposition"]
    guard.assert_awaited_once()
