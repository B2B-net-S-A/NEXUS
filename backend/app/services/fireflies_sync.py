"""
Fireflies.ai Auto-Sync Service
Fetches meeting transcripts via GraphQL API and links them to candidates.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.note import Note, NoteType

logger = logging.getLogger(__name__)

FIREFLIES_API_URL = "https://api.fireflies.ai/graphql"
FIREFLIES_API_KEY = os.getenv("FIREFLIES_API_KEY", "")

# In-memory state for "last sync" (in production use DB/Redis)
_last_sync_state: dict = {
    "last_synced_at": None,
    "transcript_count": 0,
    "error": None,
}

TRANSCRIPTS_QUERY = """
query GetTranscripts($fromDate: String) {
  transcripts(fromDate: $fromDate) {
    id
    title
    date
    duration
    summary {
      overview
      action_items
    }
    transcript_url
    participants
    sentences {
      text
      speaker_name
    }
  }
}
"""


def _get_headers() -> dict:
    return {
        "Authorization": f"Bearer {FIREFLIES_API_KEY}",
        "Content-Type": "application/json",
    }


async def _fetch_transcripts(since: Optional[datetime] = None) -> list:
    """Fetch transcripts from Fireflies GraphQL API."""
    variables = {}
    if since:
        # Fireflies expects ISO date string
        variables["fromDate"] = since.strftime("%Y-%m-%d")

    payload = {
        "query": TRANSCRIPTS_QUERY,
        "variables": variables,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            FIREFLIES_API_URL,
            json=payload,
            headers=_get_headers(),
        )
        response.raise_for_status()
        data = response.json()

    if "errors" in data:
        error_msgs = [e.get("message", "Unknown error") for e in data["errors"]]
        raise ValueError(f"Fireflies API errors: {'; '.join(error_msgs)}")

    return data.get("data", {}).get("transcripts", []) or []


def _extract_text(sentences: list) -> str:
    """Convert sentences list to readable transcript text."""
    if not sentences:
        return ""
    lines = []
    for s in sentences:
        speaker = s.get("speaker_name", "").strip()
        text = s.get("text", "").strip()
        if speaker:
            lines.append(f"**{speaker}:** {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def _extract_summary(summary: Optional[dict]) -> str:
    """Format summary from Fireflies."""
    if not summary:
        return ""
    parts = []
    overview = summary.get("overview", "")
    if overview:
        parts.append(f"**Podsumowanie:** {overview}")
    action_items = summary.get("action_items", "")
    if action_items:
        parts.append(f"**Działania:** {action_items}")
    return "\n\n".join(parts)


async def _find_candidate_by_emails(db: AsyncSession, participant_emails: list) -> Optional[Candidate]:
    """Find a candidate whose email matches any of the meeting participants."""
    if not participant_emails:
        return None
    for email in participant_emails:
        if not email or "@" not in email:
            continue
        result = await db.execute(
            select(Candidate).where(Candidate.email == email.lower().strip())
        )
        candidate = result.scalar_one_or_none()
        if candidate:
            return candidate
    return None


async def sync_fireflies_transcripts(db: AsyncSession) -> dict:
    """
    Main sync function. Best-effort: catches all errors gracefully.
    Returns summary: {synced, linked, errors, last_synced_at}
    """
    global _last_sync_state

    if not FIREFLIES_API_KEY:
        msg = "FIREFLIES_API_KEY nie jest skonfigurowany"
        logger.warning(msg)
        _last_sync_state["error"] = msg
        return {"synced": 0, "linked": 0, "errors": 1, "error": msg}

    synced = 0
    linked = 0
    errors = 0

    try:
        since = _last_sync_state.get("last_synced_at")
        transcripts = await _fetch_transcripts(since=since)
        logger.info(f"Fireflies: fetched {len(transcripts)} transcripts")

        for transcript in transcripts:
            try:
                t_id = transcript.get("id", "")
                title = transcript.get("title", "Spotkanie bez tytułu")
                date_str = transcript.get("date")
                participants = transcript.get("participants", []) or []
                sentences = transcript.get("sentences", []) or []
                summary = transcript.get("summary")

                # Build note content
                transcript_text = _extract_text(sentences)
                summary_text = _extract_summary(summary)

                content_parts = [f"# {title}"]
                if date_str:
                    content_parts.append(f"📅 Data: {date_str}")
                if participants:
                    content_parts.append(f"👥 Uczestnicy: {', '.join(p for p in participants if p)}")
                if summary_text:
                    content_parts.append(f"\n{summary_text}")
                if transcript_text:
                    content_parts.append(f"\n---\n## Transkrypcja\n\n{transcript_text}")

                content = "\n\n".join(content_parts)

                # Try to link to a candidate
                candidate = await _find_candidate_by_emails(db, participants)

                note = Note(
                    content=content,
                    note_type=NoteType.meeting,
                    candidate_id=candidate.id if candidate else None,
                    author_id=None,  # system-generated
                )
                db.add(note)
                synced += 1
                if candidate:
                    linked += 1
                    logger.info(f"Fireflies: linked transcript '{title}' to candidate {candidate.id}")
                else:
                    logger.info(f"Fireflies: imported transcript '{title}' (no candidate match)")

            except Exception as exc:
                errors += 1
                logger.warning(f"Fireflies: error processing transcript {transcript.get('id', '?')}: {exc}")

        await db.commit()

        now = datetime.now(timezone.utc)
        _last_sync_state = {
            "last_synced_at": now,
            "transcript_count": _last_sync_state.get("transcript_count", 0) + synced,
            "error": None,
        }

        return {
            "synced": synced,
            "linked": linked,
            "errors": errors,
            "last_synced_at": now.isoformat(),
        }

    except Exception as exc:
        error_msg = str(exc)
        logger.error(f"Fireflies sync failed: {error_msg}")
        _last_sync_state["error"] = error_msg
        return {
            "synced": 0,
            "linked": 0,
            "errors": 1,
            "error": error_msg,
        }


def get_sync_status() -> dict:
    """Return current sync state (last sync time, transcript count, error)."""
    state = _last_sync_state.copy()
    if state.get("last_synced_at") and isinstance(state["last_synced_at"], datetime):
        state["last_synced_at"] = state["last_synced_at"].isoformat()
    return state
