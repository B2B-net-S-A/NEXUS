"""Runda 9 (R9-N10-9): CV z maila wysłanego przez rekrutera nie nadpisuje oryginału."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.core.config import settings
from app.models.m365 import EmailDirection
from app.services.m365 import attachment_handler
from app.tasks import m365_cv_parse


async def test_outgoing_mail_attachment_is_not_parsed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "M365_AUTO_PARSE_CV", True)
    attachment = SimpleNamespace(
        id=1,
        is_cv_candidate=True,
        storage_path="m365/1/cv.pdf",
        parsed_candidate_id=None,
        parse_error=None,
        cv_parse_attempted_at=None,
        sha256="abc",
    )
    email = SimpleNamespace(id=2, candidate_id=37, direction=EmailDirection.sent)
    db = SimpleNamespace(scalar=AsyncMock(), execute=AsyncMock())

    await attachment_handler.try_parse_cv(db, attachment, email)

    assert attachment.parsed_candidate_id is None
    assert attachment.parse_error == "outgoing_mail_skipped"
    db.scalar.assert_not_awaited()
    db.execute.assert_not_awaited()


def test_known_candidate_queue_takes_only_received_mail() -> None:
    source = inspect.getsource(m365_cv_parse.run_m365_cv_parse_once)
    assert "Email.direction == EmailDirection.received" in source
