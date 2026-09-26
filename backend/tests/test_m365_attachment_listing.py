"""Listowanie załączników maila bez treści i bez powtórek (runda 6 audytu, M365-9).

Do 26.09.2026 lista ``/attachments`` szła bez $select (Graph oddawał
``contentBytes`` WSZYSTKICH załączników, także za dużych), a sync wołał ją przy
każdej zmianie maila (przeczytanie, kategoria) — nawet gdy pliki już leżały
na dysku.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.m365 import attachment_handler


class _Gc:
    def __init__(self, items):
        self.items = items
        self.gets: list[tuple[str, dict | None]] = []
        self.downloads: list[str] = []

    async def get(self, url, params=None):
        self.gets.append((url, params))
        return {"value": self.items}

    async def download(self, url):
        self.downloads.append(url)
        return b"%PDF"


def _db(known):
    added = []

    def _add(row):
        added.append(row)

    return SimpleNamespace(
        scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: known)),
        scalar=AsyncMock(return_value=None),
        add=_add,
        flush=AsyncMock(),
        added=added,
    )


def _email():
    return SimpleNamespace(id=5, user_id=3, has_attachments=True, m365_message_id="m-1")


async def test_listing_has_no_content_and_downloads_only_what_fits(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    monkeypatch.setattr(attachment_handler, "M365_ROOT", tmp_path / "microsoft365")
    monkeypatch.setattr(attachment_handler.settings, "M365_MAX_ATTACHMENT_MB", 1)
    gc = _Gc(
        [
            {"id": "a1", "name": "cv.pdf", "contentType": "application/pdf", "size": 10},
            {
                "id": "a2",
                "name": "wielki.pdf",
                "contentType": "application/pdf",
                "size": 5 * 1024 * 1024,
            },
        ]
    )
    db = _db([])

    rows = await attachment_handler.download_for_email(db, gc, _email())

    url, params = gc.gets[0]
    assert "contentBytes" not in params["$select"]
    assert gc.downloads == ["/me/messages/m-1/attachments/a1/$value"]
    assert rows[0].storage_path and rows[1].parse_error.startswith("size_exceeded")


async def test_already_stored_attachments_skip_graph(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    (tmp_path / "cv.pdf").write_bytes(b"%PDF")
    known = [
        SimpleNamespace(storage_path="cv.pdf", parse_error=None),
        SimpleNamespace(storage_path=None, parse_error="size_exceeded: 9 > 1"),
    ]
    gc = _Gc([])

    rows = await attachment_handler.download_for_email(_db(known), gc, _email())

    assert rows == known
    assert gc.gets == [] and gc.downloads == []


async def test_missing_file_on_disk_relists(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(attachment_handler, "STORAGE_ROOT", tmp_path)
    known = [SimpleNamespace(storage_path="zniknal.pdf", parse_error=None)]
    gc = _Gc([])

    await attachment_handler.download_for_email(_db(known), gc, _email())

    assert len(gc.gets) == 1
