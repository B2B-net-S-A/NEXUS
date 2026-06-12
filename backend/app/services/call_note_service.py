"""Turn a call transcript into a factual Polish note attached to the candidate.

Reuses the map-reduce transcript summarizer from
:mod:`app.services.champion_draft_service` (so long transcripts keep context),
then asks Claude for a concise, FACTUAL Polish note and writes it to
``Call.summary`` plus a :class:`~app.models.note.Note` of type ``call`` on the
candidate timeline.

CRITICAL — EU AI Act art. 5(1)(f) prohibits inferring a candidate's emotions in a
recruitment context. The prompt below is factual-only and explicitly forbids any
mood/sentiment/personality judgement. Do not relax it.

Champion-profile enrichment (``enrich_from_call``) stays a SEPARATE, optional
downstream — this service only produces the recruiter-facing call note.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.call import Call
from app.models.note import Note, NoteType
from app.services.champion_draft_service import _summarize_transcript_for_champion

logger = logging.getLogger(__name__)

# Cheap + fast; the note is a short factual digest, not structured JSON.
CALL_NOTE_MODEL = os.environ.get("CALL_NOTE_MODEL", "claude-haiku-4-5-20251001")

# Factual-only. The negative instruction is load-bearing for AI Act compliance —
# any emotion/sentiment/personality wording must NOT be produced.
CALL_NOTE_SYSTEM_PROMPT = (
    "Jesteś asystentem rekrutera. Na podstawie transkrypcji rozmowy telefonicznej "
    "z kandydatem wypisz WYŁĄCZNIE fakty, po polsku, w zwięzłych punktach: "
    "omawiane stanowisko i technologie, doświadczenie, dostępność, oczekiwania "
    "finansowe, okres wypowiedzenia, lokalizacja/tryb pracy, poczynione ustalenia "
    "i następne kroki, otwarte pytania. "
    "Bezwzględny zakaz: NIE oceniaj i NIE opisuj emocji, nastroju, sentymentu, "
    "zaangażowania, stresu, osobowości ani 'dopasowania kulturowego' kandydata; "
    "nie spekuluj o jego stanie wewnętrznym. Trzymaj się tego, co padło w rozmowie. "
    "Jeśli jakiejś informacji brak — po prostu ją pomiń. Bez wstępu, bez meta-"
    "komentarza, bez podsumowania na końcu."
)


def build_call_note_prompt(transcript: str) -> tuple[str, str]:
    """Return ``(system_prompt, user_prompt)`` for the call-note LLM call.

    Pure helper, extracted for testability (a test asserts the prompt carries no
    emotion/sentiment instruction and embeds the transcript).
    """
    user_prompt = (
        "Transkrypcja rozmowy (po polsku):\n\n"
        f"{transcript}\n\n"
        "Wypisz notatkę faktograficzną według reguł systemowych."
    )
    return CALL_NOTE_SYSTEM_PROMPT, user_prompt


def _generate_note_sync(transcript: str, *, model: str) -> str:
    """Sync Claude call returning plain text. Wrapped in ``asyncio.to_thread``.

    Mirrors the sync ``anthropic.Anthropic`` pattern used elsewhere in the
    codebase (see ``champion_draft_service._summarize_chunk_sync``).
    """
    import anthropic  # noqa: PLC0415 — local import, avoid import cost at load

    api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not configured")

    system_prompt, user_prompt = build_call_note_prompt(transcript)
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=1200,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    parts: list[str] = []
    for block in getattr(message, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text or "")
    return "\n".join(p for p in parts if p.strip()).strip()


def _recording_proxy_url(call_id: int) -> str:
    """Authed proxy URL for the recording (served by /api/dialer/calls/{id}/recording)."""
    base = settings.PUBLIC_API_BASE_URL.rstrip("/")
    return f"{base}/api/dialer/calls/{call_id}/recording"


async def summarize_call(
    db: AsyncSession,
    *,
    call_id: int,
    transcript: str,
    recording_available: bool = False,
) -> Optional[Note]:
    """Generate the factual note for a call and persist it.

    - Map-reduces long transcripts (reused helper) before the final LLM call.
    - Writes the note to ``Call.summary`` and ``Call.transcript``.
    - Creates a ``Note(note_type=call)`` on the candidate (idempotent by
      ``source_ref="dialer:<call_id>"``).

    Returns the created/existing Note, or ``None`` when there is nothing to
    summarize. The caller commits the session.
    """
    transcript = (transcript or "").strip()
    if not transcript:
        logger.info("call_note: call %s has empty transcript — skipping", call_id)
        return None

    call = await db.get(Call, call_id)
    if call is None:
        logger.warning("call_note: call %s not found — skipping", call_id)
        return None

    condensed = await _summarize_transcript_for_champion(transcript)
    note_text = await asyncio.to_thread(
        _generate_note_sync, condensed, model=CALL_NOTE_MODEL
    )
    if not note_text:
        logger.warning("call_note: LLM produced empty note for call %s", call_id)
        return None

    call.transcript = transcript
    call.summary = note_text

    source_ref = f"dialer:{call_id}"
    existing = await db.execute(select(Note).where(Note.source_ref == source_ref))
    note = existing.scalar_one_or_none()
    if note is not None:
        note.content = note_text
        logger.info("call_note: updated existing note for call %s", call_id)
        return note

    note = Note(
        content=note_text,
        note_type=NoteType.call,
        candidate_id=call.candidate_id,
        author_id=call.user_id,
        source_ref=source_ref,
        audio_url=_recording_proxy_url(call_id) if recording_available else None,
    )
    db.add(note)
    logger.info(
        "call_note: created note for call %s (candidate %s)",
        call_id,
        call.candidate_id,
    )
    return note
