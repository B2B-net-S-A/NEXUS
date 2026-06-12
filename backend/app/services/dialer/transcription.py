"""Background transcription pipeline: recording → AssemblyAI (Polish) → note.

Runs OFF the webhook request path (fire-and-forget) so a slow STT job never
blocks the gateway callback. Each run opens its own DB session.

Flow: fetch the recording bytes → upload to AssemblyAI (EU) → submit Polish
transcription → poll → hand the text to :func:`call_note_service.summarize_call`
(which writes ``Call.summary`` + a candidate ``Note``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from app.core.database import AsyncSessionLocal
from app.services.assemblyai import AssemblyAIClient, AssemblyAIConfig
from app.services.call_note_service import summarize_call

logger = logging.getLogger(__name__)


async def _fetch_recording(url: str) -> bytes:
    """Download the recording bytes from the gateway/storage URL."""
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as http:
        resp = await http.get(url)
        resp.raise_for_status()
        return resp.content


async def run_transcription(
    call_id: int, *, recording_url: str, dual_channel: bool = False
) -> Optional[str]:
    """Transcribe a recording and write the call note. Returns the text.

    Raises are caught by :func:`schedule_transcription`; here we let them
    propagate so the function is unit-testable.
    """
    cfg = AssemblyAIConfig.from_settings()
    audio = await _fetch_recording(recording_url)
    async with AssemblyAIClient(cfg) as client:
        upload_url = await client.upload(audio)
        transcript_id = await client.submit_transcription(
            upload_url, language_code="pl", dual_channel=dual_channel
        )
        result = await client.poll_transcription(transcript_id)
    text = (result.get("text") or "").strip()
    if not text:
        logger.warning("dialer transcription: empty text for call %s", call_id)
        return None

    async with AsyncSessionLocal() as db:
        await summarize_call(
            db, call_id=call_id, transcript=text, recording_available=True
        )
        await db.commit()
    return text


def schedule_transcription(
    call_id: int, recording_url: str, *, dual_channel: bool = False
) -> "asyncio.Task":
    """Fire-and-forget the transcription task with error logging."""

    async def _runner() -> None:
        try:
            await run_transcription(
                call_id, recording_url=recording_url, dual_channel=dual_channel
            )
        except Exception as exc:  # noqa: BLE001 — background task, log + swallow
            logger.error("dialer transcription failed for call %s: %s", call_id, exc)

    return asyncio.create_task(_runner())
