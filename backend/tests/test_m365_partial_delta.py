"""Aktualizacja delty bez treści nie kasuje zapisanego maila (02.11.2026).

Delta Graph potrafi oddać zmienioną wiadomość bez ``body`` (zwykle samo ``id``
i ``isRead`` po przeczytaniu). Sync czytał brak klucza jak pustą wartość, więc
przeczytany mail tracił treść, podgląd i flagę załączników. Pomiar 02.11:
2782 wiersze z 13 skrzynek, 1477 przy kandydatach.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.core.config import settings
from app.models.m365 import EmailMatchMethod
from app.services.m365 import attachment_handler
from app.services.m365 import sync as sync_mod

CONN = SimpleNamespace(id=1, user_id=3, mailbox_upn="me@example.com")


def _stored(**kw) -> SimpleNamespace:
    base = dict(
        id=5,
        candidate_id=77,
        match_method=EmailMatchMethod.strict,
        match_confidence=1.0,
        matched_at=None,
        matched_by_user_id=None,
        is_read=False,
        body_html="<p>treść</p>",
        body_text="treść",
        body_preview="treść",
        has_attachments=True,
        raw_categories=["Ważne"],
        is_private_filtered=False,
        web_link="https://outlook.example/1",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _db(existing) -> SimpleNamespace:
    nested = MagicMock()
    nested.__aenter__ = AsyncMock(return_value=None)
    nested.__aexit__ = AsyncMock(return_value=False)
    return SimpleNamespace(
        scalar=AsyncMock(return_value=existing),
        add=MagicMock(),
        flush=AsyncMock(),
        begin_nested=MagicMock(return_value=nested),
    )


def _no_side_calls(monkeypatch) -> SimpleNamespace:
    calls = SimpleNamespace(
        download=AsyncMock(return_value=[]),
        match=AsyncMock(
            return_value=SimpleNamespace(
                candidate_id=None, method="unmatched", confidence=None
            )
        ),
    )
    monkeypatch.setattr(attachment_handler, "download_for_email", calls.download)
    monkeypatch.setattr(sync_mod.matcher, "match", calls.match)
    return calls


async def test_read_change_without_body_keeps_stored_mail(monkeypatch) -> None:
    calls = _no_side_calls(monkeypatch)
    row = _stored()

    result = await sync_mod._upsert_message(
        _db(row), None, CONN, {"id": "graph-1", "isRead": True}, "Inbox"
    )

    assert result is row
    assert row.is_read is True
    assert row.body_html == "<p>treść</p>"
    assert row.body_text == "treść"
    assert row.body_preview == "treść"
    assert row.has_attachments is True
    assert row.raw_categories == ["Ważne"]
    assert row.candidate_id == 77
    calls.download.assert_not_awaited()
    calls.match.assert_not_awaited()


async def test_update_without_is_read_keeps_read_state(monkeypatch) -> None:
    _no_side_calls(monkeypatch)
    row = _stored(is_read=True)

    await sync_mod._upsert_message(
        _db(row), None, CONN, {"id": "graph-1", "categories": []}, "Inbox"
    )

    assert row.is_read is True
    assert row.raw_categories == []
    assert row.body_text == "treść"


async def test_update_without_body_for_unknown_message_adds_no_row(monkeypatch) -> None:
    # Pomiar 02.11: 15 wierszy bez nadawcy, tematu i treści z takich aktualizacji.
    _no_side_calls(monkeypatch)
    db = _db(None)

    result = await sync_mod._upsert_message(
        db, None, CONN, {"id": "graph-unknown", "isRead": True}, "Inbox"
    )

    assert result is None
    db.add.assert_not_called()


async def test_empty_body_does_not_erase_stored_content(monkeypatch) -> None:
    _no_side_calls(monkeypatch)
    row = _stored()
    msg = {
        "id": "graph-1",
        "isRead": True,
        "hasAttachments": True,
        "body": {"contentType": "html", "content": ""},
        "bodyPreview": "",
    }

    await sync_mod._upsert_message(_db(row), None, CONN, msg, "Inbox")

    assert row.body_html == "<p>treść</p>"
    assert row.body_text == "treść"
    assert row.body_preview == "treść"


async def test_new_body_replaces_stored_content(monkeypatch) -> None:
    _no_side_calls(monkeypatch)
    row = _stored()
    msg = {
        "id": "graph-1",
        "isRead": True,
        "hasAttachments": False,
        "body": {"contentType": "html", "content": "<p>nowa</p>"},
        "bodyPreview": "nowa",
    }

    await sync_mod._upsert_message(_db(row), None, CONN, msg, "Inbox")

    assert "nowa" in row.body_html
    assert "nowa" in row.body_text
    assert row.body_preview == "nowa"
    assert row.has_attachments is False


async def test_private_category_still_erases_content(monkeypatch) -> None:
    # Kategoria prywatna to decyzja właściciela skrzynki: tu pustka jest celowa.
    _no_side_calls(monkeypatch)
    row = _stored()
    msg = {
        "id": "graph-1",
        "isRead": True,
        "categories": [settings.M365_IGNORE_CATEGORY],
        "body": {"contentType": "html", "content": "<p>prywatne</p>"},
        "bodyPreview": "prywatne",
    }

    await sync_mod._upsert_message(_db(row), None, CONN, msg, "Inbox")

    assert row.is_private_filtered is True
    assert row.body_html is None
    assert row.body_text is None
    assert row.body_preview is None


async def test_private_category_without_body_erases_content(monkeypatch) -> None:
    _no_side_calls(monkeypatch)
    row = _stored()
    msg = {"id": "graph-1", "categories": [settings.M365_IGNORE_CATEGORY]}

    await sync_mod._upsert_message(_db(row), None, CONN, msg, "Inbox")

    assert row.is_private_filtered is True
    assert row.body_html is None
    assert row.body_text is None
    assert row.body_preview is None
    assert row.has_attachments is False


async def test_read_change_keeps_private_mail_private(monkeypatch) -> None:
    # Bez klucza ``categories`` sync zdejmował znacznik prywatności.
    _no_side_calls(monkeypatch)
    row = _stored(
        is_private_filtered=True,
        body_html=None,
        body_text=None,
        body_preview=None,
        has_attachments=False,
        raw_categories=[settings.M365_IGNORE_CATEGORY],
    )

    await sync_mod._upsert_message(
        _db(row), None, CONN, {"id": "graph-1", "isRead": True}, "Inbox"
    )

    assert row.is_private_filtered is True
    assert row.raw_categories == [settings.M365_IGNORE_CATEGORY]
    assert row.body_text is None
