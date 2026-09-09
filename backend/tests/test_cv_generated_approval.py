import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services.cv_generated_approval import approved_version_for_generation


@pytest.mark.parametrize(
    "case",
    ["valid", "missing", "corrupt_html", "corrupt_docx", "no_artifact", "unassigned"],
)
async def test_only_exact_associated_intact_version_can_be_selected(case):
    generated = SimpleNamespace(
        id=7, candidate_id=None if case == "unassigned" else 2, job_id=3
    )
    version = SimpleNamespace(
        content_html="<p>Approved</p>",
        docx_content=b"approved",
        content_sha256=hashlib.sha256(b"<p>Approved</p>").hexdigest(),
        docx_sha256=hashlib.sha256(b"approved").hexdigest(),
    )
    if case == "corrupt_html":
        version.content_html += "changed"
    if case == "corrupt_docx":
        version.docx_content += b"changed"
    if case == "no_artifact":
        version.docx_content = None
    db = SimpleNamespace(
        scalar=AsyncMock(return_value=None if case == "missing" else version)
    )
    if case == "valid":
        assert await approved_version_for_generation(db, generated, 12) is version
    else:
        with pytest.raises(HTTPException) as error:
            await approved_version_for_generation(db, generated, 12)
        assert error.value.status_code == (404 if case == "missing" else 409)
    if case == "unassigned":
        db.scalar.assert_not_awaited()
    else:
        sql = str(db.scalar.call_args.args[0].compile())
        assert "generated_document_id =" in sql
        assert "candidate_id =" in sql
        assert "job_id =" in sql
        assert "cv_document_versions.id =" in sql


@pytest.mark.parametrize("pinned", [False, True])
async def test_public_link_uses_selected_approval_without_original_claims(
    monkeypatch, pinned
):
    from unittest.mock import Mock
    from starlette.requests import Request
    from starlette.responses import Response
    from app.api import public_share as api
    import app.services.cv_generated_approval as approval

    doc = SimpleNamespace(
        id=7,
        status="ready",
        mode="upload",
        candidate_id=2,
        render_payload={
            "name": "Original",
            "position": "Original title",
            "language": "pl",
        },
        requirement_map={"items": [{"requirement": "Original skill"}]},
    )
    row = SimpleNamespace(
        token="revocation",
        document_version_id=12 if pinned else None,
        generated_document=doc,
        expires_at=None,
    )
    version = SimpleNamespace(
        content_html="<p>Approved edit</p>",
        language="en",
        candidate_first_name="Approved",
        job_title="Approved title",
    )
    resolver = AsyncMock(return_value=version)
    flags = AsyncMock(return_value=(True, True))
    monkeypatch.setattr(api, "_load_generated_share", AsyncMock(return_value=row))
    monkeypatch.setattr(api, "_interactive_flags", flags)
    monkeypatch.setattr(approval, "approved_version_for_generation", resolver)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: 1)),
        add=Mock(),
        commit=AsyncMock(),
    )
    response = Response()
    result = await api.get_public_generated_cv.__wrapped__(
        token="secret",
        request=Request({"type": "http", "method": "GET", "path": "/"}),
        response=response,
        db=db,
    )
    assert response.headers["Cache-Control"] == "no-store"
    if pinned:
        resolver.assert_awaited_once_with(db, doc, 12)
        flags.assert_not_awaited()
        assert result["cv_html"] == version.content_html
        assert result["cv"]["position"] == "Approved title"
        assert result["requirements"] is None
        assert result["chat_enabled"] is False
        assert "Original" not in str(result)
    else:
        resolver.assert_not_awaited()
        assert result["cv_html"] is None
        assert result["cv"]["position"] == "Original title"
        assert result["chat_enabled"] is True
