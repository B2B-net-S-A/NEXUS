"""CV-06: client opt-out applies to upload and recruitment documents alike."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api.cv_generator_b2b import _interactive_available
from app.api.public_share import _interactive_flags
from app.models.client import Client
from app.models.job import Job
from app.services.cv_generator_b2b.document_policy import interactive_client_enabled


def document(**overrides):
    return SimpleNamespace(
        **dict(
            dict(client_id=26, job_id=None, mode="upload", requirement_map={"items": [1]}),
            **overrides,
        )
    )


@pytest.mark.parametrize("mode", ["upload", "new"])
async def test_explicit_client_opt_out_disables_share_tiles_and_public_chat(mode):
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(cv_interactive_enabled=False)
    doc = document(mode=mode)
    assert await _interactive_available(db, doc) is False
    assert await _interactive_flags(db, doc) == (False, False)
    assert all(call.args == (Client, 26) for call in db.get.call_args_list)


async def test_explicit_document_client_wins_over_job_client():
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(cv_interactive_enabled=False)
    assert not await interactive_client_enabled(db, document(job_id=42))
    db.get.assert_awaited_once_with(Client, 26)


async def test_legacy_job_fallback_uses_same_client_policy():
    db = AsyncMock()
    db.get.side_effect = [
        SimpleNamespace(client_id=26),
        SimpleNamespace(cv_interactive_enabled=False),
    ]
    assert not await interactive_client_enabled(db, document(client_id=None, job_id=42))
    assert [c.args for c in db.get.call_args_list] == [(Job, 42), (Client, 26)]


async def test_unassociated_upload_retains_default():
    db = AsyncMock()
    assert await interactive_client_enabled(db, document(client_id=None))
    db.get.assert_not_awaited()


async def test_missing_associated_client_fails_closed():
    db = AsyncMock()
    db.get.return_value = None
    assert not await interactive_client_enabled(db, document())


async def test_public_ai_toggle_still_controls_chat(monkeypatch):
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(cv_interactive_enabled=True)
    monkeypatch.setattr(
        "app.services.ai_quota.get_master_enabled", AsyncMock(return_value=False)
    )
    assert await _interactive_flags(db, document()) == (True, False)


async def test_html_download_excludes_requirement_tiles_for_opted_out_client():
    from app.api.cv_generator_b2b import download_generated_cv_html
    from app.models.cv_generated_document import CvGeneratedDocument

    doc = document(
        status="ready", render_payload={"name": "Test Candidate", "language": "pl"},
        filename="test.docx",
        requirement_map={"items": [{"requirement": "Python", "kind": "must"}]},
    )
    db = AsyncMock()
    db.get.side_effect = [doc, SimpleNamespace(cv_interactive_enabled=False)]
    result = await download_generated_cv_html(1, SimpleNamespace(), db)
    assert result.status_code == 200
    assert b'id="tiles"' not in result.body
    assert [c.args for c in db.get.call_args_list] == [
        (CvGeneratedDocument, 1), (Client, 26)
    ]
