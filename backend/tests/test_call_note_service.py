"""Unit tests for call_note_service — no network, no DB (db is mocked).

Guards two things: (1) the call-note prompt is factual-only and forbids emotion
inference (EU AI Act art. 5(1)(f)); (2) summarize_call writes the summary onto
the Call and creates a candidate Note(note_type=call).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.models.note import NoteType
from app.services import call_note_service
from app.services.call_note_service import build_call_note_prompt, summarize_call


def test_prompt_forbids_emotion_and_embeds_transcript():
    system, user = build_call_note_prompt("Kandydat: 5 lat w Pythonie, zdalnie.")
    assert "Pythonie" in user

    low = system.lower()
    # Must explicitly PROHIBIT emotion/sentiment, never request it.
    assert "nie oceniaj" in low
    assert "zakaz" in low
    for token in ("emocj", "nastroj", "sentyment", "osobow"):
        assert token in low  # present only inside the prohibition clause
    # Sanity: no positive instruction to judge affect.
    assert "oceń emocje" not in low
    assert "opisz nastrój" not in low


async def test_summarize_call_writes_summary_and_creates_note(monkeypatch):
    async def _fake_condense(transcript, **_kwargs):
        return transcript

    monkeypatch.setattr(
        call_note_service, "_summarize_transcript_for_champion", _fake_condense
    )
    monkeypatch.setattr(
        call_note_service,
        "_generate_note_sync",
        lambda transcript, *, model: "- Python, 5 lat\n- dostępny od zaraz",
    )

    fake_call = SimpleNamespace(
        candidate_id=5, user_id=7, summary=None, transcript=None
    )
    db = MagicMock()
    db.get = AsyncMock(return_value=fake_call)
    result_proxy = MagicMock()
    result_proxy.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=result_proxy)
    db.add = MagicMock()

    note = await summarize_call(
        db, call_id=42, transcript="rozmowa po polsku", recording_available=True
    )

    assert fake_call.summary.startswith("- Python")
    assert fake_call.transcript == "rozmowa po polsku"
    assert note is not None
    assert note.note_type == NoteType.call
    assert note.candidate_id == 5
    assert note.author_id == 7
    assert note.source_ref == "dialer:42"
    assert note.audio_url is not None
    assert note.audio_url.endswith("/api/dialer/calls/42/recording")
    db.add.assert_called_once()


async def test_summarize_call_skips_empty_transcript():
    db = MagicMock()
    db.get = AsyncMock()
    note = await summarize_call(db, call_id=1, transcript="   ")
    assert note is None
    db.get.assert_not_called()
