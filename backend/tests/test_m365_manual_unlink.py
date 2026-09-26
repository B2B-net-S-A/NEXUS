"""Ręczne odpięcie maila od kandydata jest decyzją (runda 6 audytu, M365-5).

Do 26.09.2026 „Odepnij” ustawiało ``unmatched`` bez żadnego śladu decyzji, a
sync (przy każdej zmianie wiadomości w Outlooku), rematch co godzinę i
zakładanie kandydata z CV przypinały mail z powrotem. Znacznik: ``unmatched``
+ ``matched_by_user_id`` (kto odpiął) — bez migracji.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.api.email_threads import _apply_bulk_action
from app.models.m365 import EmailMatchMethod
from app.services.m365 import attachment_handler, matcher
from app.services.m365 import sync as sync_mod

NOW = datetime(2026, 9, 26, 10, tzinfo=timezone.utc)


def _email(**kw):
    base = dict(
        id=5,
        candidate_id=77,
        match_method=EmailMatchMethod.strict,
        match_confidence=1.0,
        matched_at=None,
        matched_by_user_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_unlink_records_the_decision() -> None:
    email = _email()
    _apply_bulk_action(email, "unlink", None, user_id=12, now=NOW)
    assert email.candidate_id is None
    assert email.match_method == EmailMatchMethod.unmatched
    assert email.matched_by_user_id == 12
    assert matcher.manually_unlinked(email) is True


def test_link_clears_the_decision() -> None:
    email = _email(
        candidate_id=None,
        match_method=EmailMatchMethod.unmatched,
        matched_by_user_id=12,
    )
    _apply_bulk_action(email, "link_to_candidate", 9, user_id=13, now=NOW)
    assert matcher.manually_unlinked(email) is False


def test_matcher_unmatched_without_person_is_not_a_decision() -> None:
    email = _email(candidate_id=None, match_method=EmailMatchMethod.unmatched)
    assert matcher.manually_unlinked(email) is False


async def test_sync_does_not_relink_manually_unlinked_email(monkeypatch) -> None:
    existing = SimpleNamespace(
        id=5,
        candidate_id=None,
        match_method=EmailMatchMethod.unmatched,
        match_confidence=None,
        matched_at=NOW,
        matched_by_user_id=12,
        is_read=False,
        body_html=None,
        body_text=None,
        body_preview=None,
        has_attachments=False,
        raw_categories=[],
        is_private_filtered=False,
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=existing))
    match = AsyncMock(
        return_value=SimpleNamespace(candidate_id=77, method="strict", confidence=1.0)
    )
    monkeypatch.setattr(sync_mod.matcher, "match", match)
    conn = SimpleNamespace(id=1, user_id=3, mailbox_upn="me@b2bnetwork.pl")
    msg = {
        "id": "graph-1",
        "conversationId": "conv",
        "subject": "Re: CV",
        "from": {"emailAddress": {"address": "kandydat@firma.pl"}},
        "receivedDateTime": "2026-09-22T10:00:00Z",
        "body": {"contentType": "html", "content": "<p>x</p>"},
        "hasAttachments": False,
        "isRead": True,
    }

    row = await sync_mod._upsert_message(db, None, conn, msg, "Inbox")

    assert row is existing
    assert existing.candidate_id is None
    assert existing.matched_by_user_id == 12
    match.assert_not_awaited()


async def test_cv_identity_does_not_relink_manually_unlinked_email(monkeypatch) -> None:
    monkeypatch.setattr(attachment_handler.settings, "M365_AUTO_PARSE_CV", True)
    monkeypatch.setattr(
        attachment_handler.settings, "M365_AUTO_CREATE_CANDIDATE_FROM_CV", True
    )
    email = _email(
        candidate_id=None,
        match_method=EmailMatchMethod.unmatched,
        matched_by_user_id=12,
        is_private_filtered=False,
    )
    attachment = SimpleNamespace(
        is_cv_candidate=True, storage_path="x.pdf", parse_error=None
    )
    assert (
        await attachment_handler.try_create_candidate_from_cv(None, attachment, email)
        is None
    )
    # Nic nie było czytane — decyzja rekrutera zatrzymuje ścieżkę na wejściu.
    assert attachment.parse_error is None
