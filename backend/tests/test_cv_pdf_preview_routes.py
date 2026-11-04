"""Trasy stron PDF CV (Edytor CV 3, J2): transakcja kończy się przed zamianą.

Zamiana w LibreOffice może czekać na miejsce do 30 s i trwać do 45 s. Edytor
wyniku generatora czyta szkic z `FOR UPDATE` — gdyby blokady wisiały do końca
zamiany, autozapis tego samego CV stałby razem z nią. Test bez bazy: trasy
wołane bez limitu żądań (`__wrapped__`), zależności podmienione.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import cv_pdf_preview as routes
from app.services.cv_pdf_preview import PdfPreviewUnavailable


class _Db:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def commit(self) -> None:
        self.events.append("commit")

    async def get(self, model, key):
        return None


def _generated_route(monkeypatch, events: list[str], convert) -> None:
    async def load(db, generated_id, user, *, persist):
        events.append("lock")
        return SimpleNamespace(branded_version=3)

    async def render(draft, html):
        return b"PK docx"

    async def log(*args, **kwargs):
        events.append("log")

    monkeypatch.setattr(routes, "_load_generated_editor", load)
    monkeypatch.setattr(
        routes.consent_gate, "ensure_copy_downloadable", lambda *a, **k: None
    )
    monkeypatch.setattr(routes, "check_revision", lambda *a, **k: None)
    monkeypatch.setattr(routes.generated_editor, "render", render)
    monkeypatch.setattr(routes, "pdf_from_docx", convert)
    monkeypatch.setattr(routes, "_log_generated_download", log)


async def _call(events: list[str]):
    return await routes.preview_generated_cv_pdf.__wrapped__(
        request=None,
        generated_id=7,
        payload=SimpleNamespace(expected_revision=1, content_html="<p>CV</p>"),
        current_user=SimpleNamespace(id=1),
        db=_Db(events),
        intent="download",
        surface="editor",
    )


async def test_generated_preview_releases_row_locks_before_conversion(monkeypatch):
    events: list[str] = []

    async def convert(docx: bytes) -> bytes:
        events.append("convert")
        return b"%PDF-1.7"

    _generated_route(monkeypatch, events, convert)
    response = await _call(events)

    assert response.status_code == 200
    assert response.body == b"%PDF-1.7"
    assert events.index("lock") < events.index("commit") < events.index("convert")
    # Wpis pobrania po zamianie, we własnej transakcji.
    assert events.index("convert") < events.index("log") < len(events) - 1
    assert events[-1] == "commit"


async def test_conversion_failure_is_503_with_polish_message(monkeypatch):
    events: list[str] = []

    async def convert(docx: bytes) -> bytes:
        events.append("convert")
        raise PdfPreviewUnavailable("busy")

    _generated_route(monkeypatch, events, convert)
    with pytest.raises(HTTPException) as caught:
        await _call(events)

    assert caught.value.status_code == 503
    assert caught.value.detail == routes.MSG_UNAVAILABLE
    assert "log" not in events, "odmowa nie liczy się jako pobranie"
