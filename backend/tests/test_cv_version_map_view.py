import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.cv_version_map_view import approved_map_view


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "missing",
        "queued",
        "running",
        "failed",
        "interrupted",
        "html",
        "content",
        "snapshot",
    ],
)
async def test_only_matching_complete_map_is_visible(case):
    html = "<p>AWS szkoleniowo.</p>"
    digest = hashlib.sha256(html.encode()).hexdigest()
    version = SimpleNamespace(
        id=7, content_html=html, content_sha256=digest, language="pl"
    )
    result = {
        "snapshot_sha256": "a" * 64,
        "content_sha256": digest,
        "items": [
            {
                "requirement": "AWS",
                "kind": "must",
                "status": "confirmed",
                "evidence": [{"quote": "AWS szkoleniowo."}],
            }
        ],
    }
    job = SimpleNamespace(
        content_sha256=digest, input_sha256="a" * 64, status="complete", result=result
    )
    if case in {"queued", "running", "failed", "interrupted"}:
        job.status = case
    elif case == "html":
        version.content_html = "<p>Changed</p>"
    elif case == "content":
        result["content_sha256"] = "b" * 64
    elif case == "snapshot":
        result["snapshot_sha256"] = "b" * 64
    db = AsyncMock()
    db.get.return_value = None if case == "missing" else job
    status, items = await approved_map_view(db, version)
    if case == "valid":
        assert status == "complete"
        assert items[0]["requirement"] == "AWS"
    else:
        assert status != "complete"
        assert items == []
    db.commit.assert_not_awaited()
