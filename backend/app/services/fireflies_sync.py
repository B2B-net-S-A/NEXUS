"""
Fireflies.ai Auto-Sync Service
Fetches meeting transcripts via GraphQL API and links them to candidates.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from sqlalchemy import literal_column, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.note import Note, NoteType

logger = logging.getLogger(__name__)

FIREFLIES_API_URL = "https://api.fireflies.ai/graphql"
FIREFLIES_API_KEY = os.getenv("FIREFLIES_API_KEY", "")

# In-memory state for "last sync" (in production use DB/Redis)
#
# INT-11: `last_synced_at` to WATERMARK (= chwila startu ostatniego biegu bez
# błędów) i przesuwa się wyłącznie przy `errors == 0`. Do 09.2026 przesuwał
# się po każdym biegu, więc transkrypt, który padł na przetwarzaniu, wypadał
# z okna na zawsze. `last_attempt_at` i `last_success_at` są osobne: pierwsza
# mówi, że pętla żyje, druga — kiedy dane były ostatnio kompletne.
_last_sync_state: dict = {
    "last_synced_at": None,
    "last_attempt_at": None,
    "last_success_at": None,
    "transcript_count": 0,
    "error": None,
}

# INT-12: Fireflies zwraca domyślnie i najwyżej 50 transkryptów na żądanie;
# bez `skip` każdy starszy ponad pierwszą stronę przepadał.
PAGE_SIZE = 50
MAX_PAGES = 200

TRANSCRIPTS_QUERY = """
query GetTranscripts($fromDate: DateTime, $limit: Int, $skip: Int) {
  transcripts(fromDate: $fromDate, limit: $limit, skip: $skip) {
    id
    title
    date
    duration
    summary {
      overview
      action_items
    }
    transcript_url
    audio_url
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


def _iso_datetime(value: datetime) -> str:
    """INT-13: `fromDate` to skalar `DateTime` — pełny ISO 8601 w UTC.

    Do 09.2026 szła sama data (`%Y-%m-%d`) w zmiennej typu `String`, więc
    watermark z godziną tracił dokładność do doby, a schemat Fireflies
    odrzucał typ zmiennej.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return (
        value.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


async def _fetch_page(query: str, variables: dict) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            FIREFLIES_API_URL,
            json={"query": query, "variables": variables},
            headers=_get_headers(),
        )
        response.raise_for_status()
        return response.json()


async def _fetch_transcripts(since: Optional[datetime] = None) -> list:
    """Fetch ALL transcripts since the watermark, page by page (INT-12).

    `audio_url` is plan-gated on some Fireflies tiers — if the API rejects
    the field we retry once without it so the whole sync never breaks on a
    plan downgrade.
    """
    base_vars: dict = {"limit": PAGE_SIZE}
    if since:
        base_vars["fromDate"] = _iso_datetime(since)

    query = TRANSCRIPTS_QUERY
    out: list = []
    for page in range(MAX_PAGES):
        variables = {**base_vars, "skip": page * PAGE_SIZE}
        data = await _fetch_page(query, variables)
        if "errors" in data:
            error_msgs = [e.get("message", "Unknown error") for e in data["errors"]]
            joined = "; ".join(error_msgs)
            if "audio_url" in joined and "audio_url" in query:
                logger.warning(
                    "Fireflies: audio_url niedostępny na tym planie — retry bez pola"
                )
                query = query.replace("    audio_url\n", "")
                data = await _fetch_page(query, variables)
                if "errors" in data:
                    error_msgs = [
                        e.get("message", "Unknown error") for e in data["errors"]
                    ]
                    raise ValueError(f"Fireflies API errors: {'; '.join(error_msgs)}")
            else:
                raise ValueError(f"Fireflies API errors: {joined}")
        batch = (data.get("data") or {}).get("transcripts") or []
        out.extend(batch)
        if len(batch) < PAGE_SIZE:
            return out
    raise ValueError(
        f"Fireflies: przekroczono limit {MAX_PAGES} stron — watermark bez zmian"
    )


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


async def _find_candidate_by_emails(
    db: AsyncSession, participant_emails: list
) -> Optional[Candidate]:
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


async def _insert_meeting_note_if_absent(
    db: AsyncSession,
    *,
    content: str,
    candidate_id: Optional[int],
    job_id: Optional[int],
    source_ref: Optional[str],
    audio_url: Optional[str],
) -> Optional[int]:
    """Insert a Fireflies meeting note, atomically deduped by ``source_ref``.

    Returns the new note id, or ``None`` when a concurrent sync already imported
    a note with the same ``source_ref``. The dedup is race-proof: the partial
    unique index ``ux_notes_source_ref_fireflies`` arbitrates the
    ``INSERT ... ON CONFLICT DO NOTHING``, so two overlapping syncs can never
    both insert (the pre-flight SELECT in the caller only handles the common
    already-seen case + audio_url refresh, and by itself has a phantom-insert
    window). A row with a NULL / non-``fireflies:`` ``source_ref`` falls outside
    the partial index and always inserts.
    """
    stmt = (
        pg_insert(Note)
        .values(
            content=content,
            note_type=NoteType.meeting,
            candidate_id=candidate_id,
            job_id=job_id,
            author_id=None,  # system-generated
            source_ref=source_ref,
            audio_url=audio_url,
        )
        .on_conflict_do_nothing(
            index_elements=[Note.source_ref],
            # Predykat LITERAŁEM, nie parametrem: Postgres dopasowuje indeks
            # częściowy do ON CONFLICT przy planowaniu i z `$n` nie zawsze umie
            # udowodnić implikację — „no unique or exclusion constraint
            # matching the ON CONFLICT” (odtworzone w teście paginacji: zapis
            # padał, a transakcja biegu stawała do końca).
            index_where=Note.source_ref.like(literal_column("'fireflies:%'")),
        )
        .returning(Note.id)
    )
    return await db.scalar(stmt)


async def sync_fireflies_transcripts(db: AsyncSession) -> dict:
    """
    Main sync function. Best-effort: catches all errors gracefully.
    Returns summary: {synced, linked, errors, last_synced_at}
    """
    global _last_sync_state

    attempt_at = datetime.now(timezone.utc)
    _last_sync_state["last_attempt_at"] = attempt_at

    if not FIREFLIES_API_KEY:
        msg = "FIREFLIES_API_KEY nie jest skonfigurowany"
        logger.warning(msg)
        _last_sync_state["error"] = msg
        return {"synced": 0, "linked": 0, "errors": 1, "error": msg}

    synced = 0
    linked = 0
    errors = 0
    # Collected per-note enrichment jobs — processed after commit so each
    # suggestion lives in its own transaction and one failing call doesn't
    # abort the whole sync.
    enrichment_jobs: list[dict] = []

    try:
        since = _last_sync_state.get("last_synced_at")
        transcripts = await _fetch_transcripts(since=since)
        logger.info(f"Fireflies: fetched {len(transcripts)} transcripts")

        for transcript in transcripts:
            try:
                # Savepoint per transkrypt: błąd bazy w jednym nie może
                # zatruć transakcji całego biegu (wszystkie następne padały).
                async with db.begin_nested():
                    transcript_id = transcript.get("id", "")
                    title = transcript.get("title", "Spotkanie bez tytułu")
                    date_str = transcript.get("date")
                    participants = transcript.get("participants", []) or []
                    sentences = transcript.get("sentences", []) or []
                    summary = transcript.get("summary")
                    audio_url = transcript.get("audio_url") or None
                    source_ref = f"fireflies:{transcript_id}" if transcript_id else None

                    # Dedup: `last_synced_at` is in-memory, so after a backend
                    # restart the same transcripts come back — skip ones we
                    # already imported (and refresh their audio_url, which the
                    # pre-0129 rows never captured).
                    if source_ref:
                        existing = await db.scalar(
                            select(Note).where(Note.source_ref == source_ref)
                        )
                        if existing:
                            if audio_url and not existing.audio_url:
                                existing.audio_url = audio_url
                            continue

                    # Build note content
                    transcript_text = _extract_text(sentences)
                    summary_text = _extract_summary(summary)

                    content_parts = [f"# {title}"]
                    if date_str:
                        content_parts.append(f"📅 Data: {date_str}")
                    if participants:
                        content_parts.append(
                            f"👥 Uczestnicy: {', '.join(p for p in participants if p)}"
                        )
                    if summary_text:
                        content_parts.append(f"\n{summary_text}")
                    if transcript_text:
                        content_parts.append(
                            f"\n---\n## Transkrypcja\n\n{transcript_text}"
                        )

                    content = "\n\n".join(content_parts)

                    # Try to link to a candidate
                    candidate = await _find_candidate_by_emails(db, participants)

                    # Phase 14: match the meeting to an open Job.
                    # Only auto-attach when the top candidate is unambiguous AND
                    # scores above the auto threshold — otherwise we leave job_id
                    # null and the DL can pick from the "Sugerowane meetingi"
                    # panel in the Job detail view.
                    from app.services.fireflies_job_matcher import (
                        SCORE_AUTO,
                        match_meeting_to_jobs,
                    )

                    matches = await match_meeting_to_jobs(
                        db,
                        meeting_title=title,
                        participant_emails=participants,
                    )
                    auto_job_id: Optional[int] = None
                    if len(matches) == 1 or (
                        len(matches) >= 2
                        and matches[0].score >= SCORE_AUTO
                        and matches[0].score - matches[1].score >= 0.1
                    ):
                        if matches[0].score >= SCORE_AUTO:
                            auto_job_id = matches[0].job_id

                    note_id = await _insert_meeting_note_if_absent(
                        db,
                        content=content,
                        candidate_id=candidate.id if candidate else None,
                        job_id=auto_job_id,
                        source_ref=source_ref,
                        audio_url=audio_url,
                    )
                    if note_id is None:
                        # A concurrent sync already imported this transcript — skip
                        # (its own pass counts + enriches it).
                        continue
                    synced += 1
                    if candidate:
                        linked += 1
                        logger.info(
                            f"Fireflies: linked transcript '{title}' to candidate {candidate.id}"
                        )
                    else:
                        logger.info(
                            f"Fireflies: imported transcript '{title}' (no candidate match)"
                        )
                    if auto_job_id:
                        logger.info(
                            "Fireflies: auto-attached meeting '%s' to job %d (score=%.2f)",
                            title,
                            auto_job_id,
                            matches[0].score,
                        )
                        # Defer enrichment — we need the committed Note + source_ref.
                        enrichment_jobs.append(
                            {
                                "job_id": auto_job_id,
                                "meeting_title": title,
                                "meeting_summary": summary_text,
                                "meeting_transcript": transcript_text,
                                "source_ref": transcript.get("id"),
                            }
                        )

            except Exception as exc:
                errors += 1
                logger.warning(
                    f"Fireflies: error processing transcript {transcript.get('id', '?')}: {exc}"
                )

        await db.commit()

        # Phase 14: fire LLM enrichment for each auto-attached meeting.
        # Done in-sequence to stay inside Claude API rate limits; each call is
        # best-effort and cannot fail the sync.
        enriched = 0
        for ej in enrichment_jobs:
            try:
                from app.services.champion_draft_service import enrich_from_meeting

                await enrich_from_meeting(
                    db,
                    job_id=ej["job_id"],
                    meeting_title=ej["meeting_title"],
                    meeting_summary=ej["meeting_summary"],
                    meeting_transcript=ej["meeting_transcript"],
                    source_ref=ej["source_ref"],
                    user_id=None,
                )
                enriched += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Fireflies: enrichment for job %s failed: %s",
                    ej["job_id"],
                    exc,
                )

        now = datetime.now(timezone.utc)
        _last_sync_state["transcript_count"] = (
            _last_sync_state.get("transcript_count", 0) + synced
        )
        if errors == 0:
            # Watermark = start TEGO biegu: transkrypt zapisany w Fireflies
            # w trakcie biegu wejdzie w następne okno (dedup po source_ref).
            _last_sync_state["last_synced_at"] = attempt_at
            _last_sync_state["last_success_at"] = now
            _last_sync_state["error"] = None
        else:
            _last_sync_state["error"] = (
                f"{errors} transkrypt(ów) nie udało się przetworzyć — "
                "okno synchronizacji nie zostało przesunięte"
            )

        watermark = _last_sync_state.get("last_synced_at")
        return {
            "synced": synced,
            "linked": linked,
            "enriched": enriched,
            "errors": errors,
            "last_synced_at": watermark.isoformat() if watermark else None,
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
    for key in ("last_synced_at", "last_attempt_at", "last_success_at"):
        if isinstance(state.get(key), datetime):
            state[key] = state[key].isoformat()
    return state
